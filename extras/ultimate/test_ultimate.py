"""Tests for extras/ultimate/ultimate.py, against a stub of the Ultimate's REST API.

    python3 -m unittest extras/ultimate/test_ultimate.py -v

The password file is never the real one: each test points
ULTIMATE_PASSWORD_FILE at a file of its own (or at none).
"""
import contextlib
import io
import os
import sys
import tempfile
import threading
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ultimate  # noqa: E402


class Stub(BaseHTTPRequestHandler):
    def _answer(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n) if n else b""
        self.server.seen.append((self.command, self.path, self.headers, body))
        # replies, if any are queued, one per request; then reply
        status, data = self.server.replies.pop(0) if self.server.replies else self.server.reply
        self.send_response(status)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    do_GET = do_POST = do_PUT = _answer

    def log_message(self, *args):
        pass


class UltimateTest(unittest.TestCase):
    def setUp(self):
        self.srv = HTTPServer(("127.0.0.1", 0), Stub)
        self.srv.seen = []
        self.srv.reply = (200, b"{}")
        self.srv.replies = []
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.host = "127.0.0.1:%d" % self.srv.server_port
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.pwfile = os.path.join(self.tmp.name, "password")
        saved = {k: os.environ.get(k) for k in
                 ("ULTIMATE_HOST", "ULTIMATE_PASSWORD", "ULTIMATE_PASSWORD_FILE")}
        self.addCleanup(self._restore, saved)
        os.environ["ULTIMATE_HOST"] = self.host
        os.environ.pop("ULTIMATE_PASSWORD", None)
        os.environ["ULTIMATE_PASSWORD_FILE"] = self.pwfile   # absent unless a test writes it
        self.addCleanup(self.srv.server_close)
        self.addCleanup(self.srv.shutdown)

    @staticmethod
    def _restore(saved):
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def write_password(self, text):
        with open(self.pwfile, "w") as f:
            f.write(text)

    def test_password_header(self):
        self.write_password("secret\n")
        u = ultimate.Ultimate(self.host, ultimate.find_password())
        u.request("GET", "/v1/info")
        u.reset()
        self.assertEqual(len(self.srv.seen), 2)
        for _, _, headers, _ in self.srv.seen:
            self.assertEqual(headers["X-Password"], "secret")

    def test_no_password_no_header(self):
        u = ultimate.Ultimate(self.host, ultimate.find_password())
        u.request("GET", "/v1/info")
        self.assertIsNone(self.srv.seen[0][2]["X-Password"])

    def test_env_password_beats_file(self):
        self.write_password("fromfile")
        os.environ["ULTIMATE_PASSWORD"] = "fromenv"
        self.assertEqual(ultimate.find_password(), "fromenv")

    def test_readmem_url(self):
        data = bytes(range(16))
        self.srv.reply = (200, data)
        u = ultimate.Ultimate(self.host, None)
        self.assertEqual(u.readmem(0x1C01, 16), data)
        method, path, _, _ = self.srv.seen[0]
        self.assertEqual((method, path), ("GET", "/v1/machine:readmem?address=1C01&length=16"))

    def test_writemem_posts_data(self):
        ultimate.Ultimate(self.host, None).writemem(0x1C01, b"\x01\x02")
        method, path, _, body = self.srv.seen[0]
        self.assertEqual((method, path, body), ("POST", "/v1/machine:writemem?address=1C01", b"\x01\x02"))

    def test_mount_posts_image(self):
        image = os.path.join(self.tmp.name, "x.d64")
        with open(image, "wb") as f:
            f.write(b"D64 bytes")
        ultimate.Ultimate(self.host, None).mount(image)
        method, path, _, body = self.srv.seen[0]
        self.assertEqual((method, path, body), ("POST", "/v1/drives/a:mount?type=d64", b"D64 bytes"))

    def make_image(self, name):
        image = os.path.join(self.tmp.name, name)
        with open(image, "wb") as f:
            f.write(b"img")
        return image

    def test_mount_type_from_extension(self):
        ultimate.Ultimate(self.host, None).mount(self.make_image("x.D71"))
        _, path, headers, _ = self.srv.seen[0]
        self.assertEqual(path, "/v1/drives/a:mount?type=d71")
        self.assertEqual(headers["Content-Disposition"], 'attachment; filename="x.D71"')

    def test_mount_type_option_overrides_extension(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(ultimate.main(["mount", self.make_image("x.d64"), "--type", "d81"]), 0)
        _, path, headers, _ = self.srv.seen[0]
        self.assertEqual(path, "/v1/drives/a:mount?type=d81")
        self.assertEqual(headers["Content-Disposition"], 'attachment; filename="x.d64"')

    def test_mount_unknown_extension_exits(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(ultimate.main(["mount", self.make_image("x.bin")]), 1)
        self.assertIn("--type", err.getvalue())
        self.assertEqual(self.srv.seen, [])

    def test_no_proxy(self):
        saved = {k: os.environ.get(k) for k in ("http_proxy", "HTTP_PROXY")}
        self.addCleanup(setattr, urllib.request, "_opener", None)   # runs after the restore
        self.addCleanup(self._restore, saved)
        os.environ["http_proxy"] = os.environ["HTTP_PROXY"] = "http://127.0.0.1:9"
        urllib.request._opener = None        # urlopen caches its opener, proxies and all
        ultimate.Ultimate(self.host, "secret").request("GET", "/v1/info")
        self.assertEqual(len(self.srv.seen), 1)

    def test_cli_commands(self):
        image = self.make_image("x.d64")
        for argv in (["reset"], ["drive-mode", "1571"], ["mount", image, "--mode", "readonly"],
                     ["load-rom", image, "--drive", "b"], ["unmount"]):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(ultimate.main(argv), 0)
        got = [(m, p) for m, p, _, _ in self.srv.seen]
        self.assertEqual(got, [("PUT", "/v1/machine:reset"),
                               ("PUT", "/v1/drives/a:set_mode?mode=1571"),
                               ("POST", "/v1/drives/a:mount?mode=readonly&type=d64"),
                               ("POST", "/v1/drives/b:load_rom"),
                               ("PUT", "/v1/drives/a:remove")])

    def test_cli_readmem_hexdump(self):
        self.srv.reply = (200, b"ABC")
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(ultimate.main(["readmem", "$1C01", "3"]), 0)
        self.assertIn("1C01", out.getvalue())
        self.assertIn("41 42 43", out.getvalue())

    def test_pause_resume(self):
        for argv in (["pause"], ["resume"]):
            self.assertEqual(ultimate.main(argv), 0)
        got = [(m, p) for m, p, _, _ in self.srv.seen]
        self.assertEqual(got, [("PUT", "/v1/machine:pause"), ("PUT", "/v1/machine:resume")])

    def test_petscii(self):
        self.assertEqual(ultimate.petscii(r'load"x",8{return}Run\n{147}{$93}'),
                         b'LOAD"X",8\rRUN\r\x93\x93')
        self.assertEqual(ultimate.petscii("a\nb"), b"A\rB")
        for bad in ("\u00e4", "{}", "{256}", "{x}"):
            with self.assertRaises(ValueError):
                ultimate.petscii(bad)

    def test_wait_polls_until_equal(self):
        self.srv.replies = [(200, b"\x00"), (200, b"\x00")]
        self.srv.reply = (200, b"\x2a")
        u = ultimate.Ultimate(self.host, None)
        self.assertTrue(u.wait(0x0B00, 0x2A, timeout=5, interval=0))
        self.assertEqual(len(self.srv.seen), 3)
        self.assertEqual(self.srv.seen[0][1], "/v1/machine:readmem?address=B00&length=1")

    def test_wait_times_out(self):
        self.srv.reply = (200, b"\x00")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(ultimate.main(["wait", "$0b00", "$2a", "--timeout", "0"]), 1)
        self.assertIn("$0B00 never became $2A", err.getvalue())

    def test_wait_delay_before_the_first_poll(self):
        self.srv.reply = (200, b"\x01")
        seen = []
        real = ultimate.time.sleep
        self.addCleanup(setattr, ultimate.time, "sleep", real)
        ultimate.time.sleep = lambda s: seen.append((s, len(self.srv.seen)))
        self.assertEqual(ultimate.main(["wait", "0B00", "1", "--delay", "12"]), 0)
        self.assertEqual(seen[0], (12.0, 0))           # no request before the delay
        self.assertEqual(len(self.srv.seen), 1)

    def test_type_in_lots_of_ten(self):
        self.srv.reply = (200, b"\x00")       # NDX: the buffer always empty
        self.assertEqual(ultimate.main(["type", "print 12345678\\n"]), 0)
        writes = [(p, b) for m, p, _, b in self.srv.seen if m == "POST"]
        self.assertEqual(writes, [("/v1/machine:writemem?address=34A", b"PRINT 1234"),
                                  ("/v1/machine:writemem?address=D0", b"\x0a"),
                                  ("/v1/machine:writemem?address=34A", b"5678\r"),
                                  ("/v1/machine:writemem?address=D0", b"\x05")])
        reads = [p for m, p, _, _ in self.srv.seen if m == "GET"]
        self.assertEqual(reads, ["/v1/machine:readmem?address=D0&length=1"] * 2)

    def test_type_c64_buffer(self):
        self.srv.reply = (200, b"\x00")
        self.assertEqual(ultimate.main(["type", "--c64", "run\\n"]), 0)
        writes = [(p, b) for m, p, _, b in self.srv.seen if m == "POST"]
        self.assertEqual(writes, [("/v1/machine:writemem?address=277", b"RUN\r"),
                                  ("/v1/machine:writemem?address=C6", b"\x04")])
        reads = [p for m, p, _, _ in self.srv.seen if m == "GET"]
        self.assertEqual(reads, ["/v1/machine:readmem?address=C6&length=1"])

    def test_type_waits_for_the_buffer(self):
        self.srv.replies = [(200, b"\x03")]     # 3 keys still in it, then empty
        self.srv.reply = (200, b"\x00")
        ultimate.Ultimate(self.host, None).type("x")
        got = [m for m, _, _, _ in self.srv.seen]
        self.assertEqual(got, ["GET", "GET", "POST", "POST"])

    def test_run_clears_flag_mounts_resets_waits(self):
        image = self.make_image("test.d64")
        self.srv.reply = (200, b"\x01")
        self.assertEqual(ultimate.main(["run", image, "--wait", "0B00", "1"]), 0)
        got = [(m, p) for m, p, _, _ in self.srv.seen]
        self.assertEqual(got, [("POST", "/v1/machine:writemem?address=B00"),
                               ("POST", "/v1/drives/a:mount?mode=unlinked&type=d64"),
                               ("PUT", "/v1/machine:reset"),
                               ("GET", "/v1/machine:readmem?address=B00&length=1")])
        self.assertEqual(self.srv.seen[0][3], b"\xfe")      # 1 xor $FF: not done yet

    def test_run_without_wait(self):
        self.assertEqual(ultimate.main(["run", self.make_image("test.d64")]), 0)
        got = [p for _, p, _, _ in self.srv.seen]
        self.assertEqual(got, ["/v1/drives/a:mount?mode=unlinked&type=d64", "/v1/machine:reset"])

    def test_error_exit(self):
        self.write_password("hunter2")
        self.srv.reply = (403, b"Forbidden")
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = ultimate.main(["info"])
        self.assertEqual(code, 1)
        self.assertIn("403", out.getvalue() + err.getvalue())
        self.assertNotIn("hunter2", out.getvalue() + err.getvalue())

    def test_host_unset(self):
        os.environ.pop("ULTIMATE_HOST")
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(ultimate.main(["info"]), 1)
        self.assertIn("ULTIMATE_HOST", err.getvalue())


if __name__ == "__main__":
    unittest.main()
