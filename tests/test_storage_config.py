"""Configuration tests for the encryption-key fallback path."""
from __future__ import annotations

import base64
import os
import subprocess
import unittest
from unittest.mock import patch

import storage


class EncryptionKeyConfigurationTests(unittest.TestCase):
    def test_existing_keychain_key_takes_precedence_over_environment(self) -> None:
        keychain_key = bytes(range(32))
        configured_key = bytes(reversed(range(32)))
        find_result = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout=base64.b64encode(keychain_key).decode("ascii"), stderr="",
        )
        with (
            patch.object(storage.sys, "platform", "darwin"),
            patch.object(storage.Path, "exists", return_value=True),
            patch.object(storage.subprocess, "run", return_value=find_result) as run,
            patch.dict(os.environ, {
                "PSIRT_ENCRYPTION_KEY": base64.b64encode(configured_key).decode("ascii"),
            }),
        ):
            self.assertEqual(storage._load_or_create_key(), keychain_key)
        self.assertEqual(run.call_count, 1)

    def test_configured_key_is_used_when_keychain_is_unavailable(self) -> None:
        configured_key = bytes(range(32))
        find_result = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="locked")
        with (
            patch.object(storage.sys, "platform", "darwin"),
            patch.object(storage.Path, "exists", return_value=True),
            patch.object(storage.subprocess, "run", return_value=find_result) as run,
            patch.dict(os.environ, {
                "PSIRT_ENCRYPTION_KEY": base64.b64encode(configured_key).decode("ascii"),
            }),
        ):
            self.assertEqual(storage._load_or_create_key(), configured_key)
        self.assertEqual(run.call_count, 1)

    def test_configured_key_must_decode_to_32_bytes(self) -> None:
        with (
            patch.object(storage.sys, "platform", "linux"),
            patch.dict(os.environ, {"PSIRT_ENCRYPTION_KEY": base64.b64encode(b"short").decode("ascii")}),
        ):
            with self.assertRaisesRegex(RuntimeError, "32 bytes"):
                storage._load_or_create_key()


if __name__ == "__main__":
    unittest.main()
