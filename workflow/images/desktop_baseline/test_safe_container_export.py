#!/usr/bin/env python3
"""Tests for bounded, path-safe container artifact export."""
from __future__ import annotations
import base64, json, os, subprocess, sys, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parent))
import safe_container_export as export  # noqa: E402

class EmbeddedScriptTests(unittest.TestCase):
    def test_transcript_reader_exports_only_regular_direct_jsonl_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/"sessions"; root.mkdir()
            expected=root/"session-1.jsonl"; expected.write_text('{"type":"message"}\n')
            (root/"nested").mkdir(); (root/"nested"/"ignored.jsonl").write_text("nested\n")
            outside=Path(tmp)/"outside.jsonl"; outside.write_text("outside\n")
            (root/"symlink.jsonl").symlink_to(outside)
            source=Path(tmp)/"hardlink-source.jsonl"; source.write_text("hardlink\n")
            os.link(source,root/"hardlink.jsonl")
            result=subprocess.run([sys.executable,"-c",export.TRANSCRIPT_SCRIPT,str(root)],
                                   capture_output=True,text=True,check=False)
            self.assertEqual(result.returncode,0,result.stderr)
            payload=json.loads(result.stdout)
            self.assertEqual([item["name"] for item in payload["files"]],["session-1.jsonl"])
            self.assertEqual(base64.b64decode(payload["files"][0]["data"],validate=True),expected.read_bytes())
            self.assertEqual(payload["files"][0]["mtime_ns"],expected.stat().st_mtime_ns)

    def test_transcript_reader_refuses_symlinked_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            real=Path(tmp)/"real"; real.mkdir()
            link=Path(tmp)/"link"; link.symlink_to(real,target_is_directory=True)
            result=subprocess.run([sys.executable,"-c",export.TRANSCRIPT_SCRIPT,str(link)],
                                   capture_output=True,text=True,check=False)
            self.assertNotEqual(result.returncode,0)

    def test_state_reader_returns_regular_file_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent=Path(tmp)/"desktop"; parent.mkdir()
            target=parent/"state.json"; target.write_text('{"saved":true}')
            result=subprocess.run([sys.executable,"-c",export.STATE_SCRIPT,str(parent),target.name],
                                   capture_output=True,text=True,check=False)
            self.assertEqual(result.returncode,0,result.stderr)
            payload=json.loads(result.stdout)
            self.assertEqual(payload["status"],"present")
            self.assertEqual(base64.b64decode(payload["data"],validate=True),target.read_bytes())

    def test_state_reader_reports_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent=Path(tmp)/"desktop"; parent.mkdir()
            result=subprocess.run([sys.executable,"-c",export.STATE_SCRIPT,str(parent),"missing.json"],
                                   capture_output=True,text=True,check=False)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(json.loads(result.stdout),{"status":"missing"})

    def test_state_reader_refuses_symlink_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            parent=Path(tmp)/"desktop"; parent.mkdir()
            outside=Path(tmp)/"outside.json"; outside.write_text('{"saved":true}')
            (parent/"state.json").symlink_to(outside)
            result=subprocess.run([sys.executable,"-c",export.STATE_SCRIPT,str(parent),"state.json"],
                                   capture_output=True,text=True,check=False)
            self.assertNotEqual(result.returncode,0)

class HostExportTests(unittest.TestCase):
    def test_transcript_export_uses_docker_exec_and_writes_allowlisted_file(self):
        payload={"files":[{"name":"session-1.jsonl","mtime_ns":1700000000000000000,
                           "data":base64.b64encode(b'{"event":1}\n').decode("ascii")}]}
        calls=[]
        def fake_run(args,**kwargs):
            calls.append(args)
            return SimpleNamespace(returncode=0,stdout=json.dumps(payload),stderr="")
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(export.subprocess,"run",side_effect=fake_run):
                path=export.export_transcripts("container-id","agent-1",Path(tmp)/"run",
                                              Path("/tmp/scry/.docker-transcripts"))
            saved=Path(path)/"sessions"/"session-1.jsonl"
            self.assertEqual(saved.read_bytes(),b'{"event":1}\n')
            self.assertEqual(saved.stat().st_mtime_ns,payload["files"][0]["mtime_ns"])
        self.assertEqual(len(calls),1)
        self.assertEqual(calls[0][:4],["docker","exec","container-id","python3"])
        self.assertNotIn("cp",calls[0])

    def test_transcript_export_rejects_path_traversal_name(self):
        payload={"files":[{"name":"../escape.jsonl","mtime_ns":1,"data":"eA=="}]}
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            export,"_run",return_value=SimpleNamespace(returncode=0,stdout=json.dumps(payload),stderr="")
        ):
            with self.assertRaisesRegex(RuntimeError,"unsafe or duplicate transcript name"):
                export.export_transcripts("container-id","agent-1",tmp,"/tmp/scry/.docker-transcripts")

    def test_state_reader_decodes_present_artifact_and_missing(self):
        data=b'{"saved":true}'
        present={"status":"present","data":base64.b64encode(data).decode("ascii")}
        with patch.object(export,"_run",return_value=SimpleNamespace(returncode=0,stdout=json.dumps(present),stderr="")):
            self.assertEqual(export.read_state_artifact("container-id"),data)
        with patch.object(export,"_run",return_value=SimpleNamespace(returncode=0,stdout='{"status":"missing"}',stderr="")):
            self.assertIsNone(export.read_state_artifact("container-id"))

    def test_state_writer_replaces_untrusted_path_and_fails_closed_when_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/"state.json"; target.mkdir()
            (target/"untrusted").write_text("bad")
            self.assertTrue(export.write_state_artifact(tmp,b'{"saved":true}',"state.json"))
            self.assertEqual(target.read_bytes(),b'{"saved":true}')
            self.assertFalse(export.write_state_artifact(tmp,None,"state.json"))
            self.assertFalse(target.exists())
            self.assertFalse((Path(tmp)/".state.json.copyback").exists())

    def test_state_writer_rejects_unsafe_filenames_without_mutating_workspace(self):
        invalid_names = (
            "",
            ".",
            "..",
            "../escape.json",
            "nested/state.json",
            r"..\\escape.json",
            "a" * 256,
            None,
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "workspace"
            root.mkdir()
            marker = root / "keep.txt"
            marker.write_text("keep", encoding="utf-8")
            for filename in invalid_names:
                with self.subTest(filename=filename):
                    with self.assertRaisesRegex(ValueError, "unsafe artifact filename"):
                        export.write_state_artifact(root, b'{"saved":true}', filename)
                    self.assertTrue(root.is_dir())
                    self.assertEqual(marker.read_text(encoding="utf-8"), "keep")

    def test_empty_container_id_is_noop_for_transcripts(self):
        self.assertEqual(export.export_transcripts("","agent-1","/tmp/run","/tmp/scry/.docker-transcripts"),"")

if __name__=="__main__":
    unittest.main(verbosity=2)
