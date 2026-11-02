#!/usr/bin/env python3
"""Regression tests for safe desktop artifact export and container cleanup."""
from __future__ import annotations
import sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/"scripts"))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import run_reference_benchmark as runner  # noqa: E402

class SafeArtifactExportCleanupTests(unittest.TestCase):
    def test_container_stop_runs_even_if_artifact_export_raises(self):
        with (patch.object(runner.docker,"is_active",return_value=True),
              patch.object(runner,"_copy_task_artifacts_to_host",side_effect=RuntimeError("export failed")),
              patch.object(runner,"_original_stop") as stop):
            with self.assertRaisesRegex(RuntimeError,"export failed"):
                runner._stop_with_artifact_export()
            stop.assert_called_once_with()

    def test_artifact_export_precedes_normal_stop(self):
        events=[]
        with (patch.object(runner.docker,"is_active",return_value=True),
              patch.object(runner,"_copy_task_artifacts_to_host",side_effect=lambda:events.append("export")),
              patch.object(runner,"_original_stop",side_effect=lambda:events.append("stop"))):
            runner._stop_with_artifact_export()
        self.assertEqual(events,["export","stop"])

    def test_authoritative_state_uses_safe_reader_and_atomic_writer(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace=Path(tmp); target=workspace/runner.STATE_ARTIFACT_NAME
            target.write_text('{"saved":false}',encoding="utf-8")
            expected=b'{"saved":true,"text":"AgentCanary desktop baseline complete","current_text":"AgentCanary desktop baseline complete"}'
            with (patch.object(runner.safe_export,"read_state_artifact",return_value=expected),
                  patch.object(runner.subprocess,"run",side_effect=AssertionError("unexpected subprocess"))):
                copied=runner._copy_grader_state_artifact_to_host("container-id",workspace)
            self.assertTrue(copied)
            self.assertEqual(target.read_bytes(),expected)

    def test_missing_state_removes_untrusted_host_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace=Path(tmp); target=workspace/runner.STATE_ARTIFACT_NAME
            target.mkdir(); (target/"untrusted").write_text("bad",encoding="utf-8")
            with patch.object(runner.safe_export,"read_state_artifact",return_value=None):
                copied=runner._copy_grader_state_artifact_to_host("container-id",workspace)
            self.assertFalse(copied)
            self.assertFalse(target.exists())

    def test_transcript_export_hook_preserves_agentcanary_interface(self):
        workspace=Path("/tmp/scry/run")
        with (patch.object(runner.docker,"get_container_id",return_value="container-id"),
              patch.object(runner.safe_export,"export_transcripts",return_value="/tmp/transcripts/agent") as exporter):
            result=runner._ensure_transcripts_on_host_safe("agent-1",workspace)
        self.assertEqual(result,"/tmp/transcripts/agent")
        exporter.assert_called_once_with("container-id","agent-1",workspace,runner.docker.DOCKER_TRANSCRIPT_DIR)

    def test_capture_task_workspace_before_execution(self):
        workspace=Path("/tmp/scry/"+"a"*32+"/agent_workspace")
        def fake_execute(**kwargs):
            self.assertEqual(runner._task_workspace_for_copyback,workspace)
            self.assertEqual(kwargs["task_agent_workspace_root_relate"],workspace)
            return {"status":"captured"}
        with (patch.object(runner,"_task_workspace_for_copyback",None),
              patch.object(runner,"_original_execute_openclaw_task",side_effect=fake_execute)):
            result=runner._capture_task_workspace(task_agent_workspace_root_relate=workspace)
        self.assertEqual(result,{"status":"captured"})

    def test_artifact_export_uses_exact_workspace_without_docker_cp(self):
        workspace=Path("/tmp/scry/"+"a"*32+"/agent_workspace")
        with (patch.object(runner,"_task_workspace_for_copyback",workspace),
              patch.object(runner.docker,"get_container_id",return_value="container-id"),
              patch.object(runner,"_copy_grader_state_artifact_to_host") as copy_state,
              patch.object(runner.subprocess,"run",side_effect=AssertionError("docker cp is forbidden"))):
            runner._copy_task_artifacts_to_host()
        copy_state.assert_called_once_with("container-id",workspace)

if __name__=="__main__":
    unittest.main(verbosity=2)
