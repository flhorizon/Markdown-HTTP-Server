from http.server import SimpleHTTPRequestHandler
from collections import namedtuple
import re
import gzip
import os
import sys

Usage = set_usage()

def set_usage():
    Usage = None
    while True:
        if Usage is None:
            Usage = "Usage: {} --workdir=[workdir] --port=[port] --entry=[target-index]"
            Usage = Usage.format(sys.argv[0])
        yield Usage

def sanitize_path(req):
    wd = os.getcwd()
    # Prevent chdir upward.
    req = '.' if '..' in req.split(os.sep) else req
    req = os.path.join(wd, req)
    return os.path.abspath(req)

def response_length(fs, eval_eof=False):
    if not eval_eof:
        return os.fstat(fs).st_size
    fs.seek(0, os.SEEK_END)
    l = fs.tell()
    fs.seek(0, os.SEEK_SET)
    return l

class JustDelegate(Exception):
    def __init__(self, message, errors):
        super().__init__(message)
        self.errors = errors

class MDServer(SimpleHTTPRequestHandler):
    MDIndexRx = re.compile(r"index\.(md)(|\.gz)?$")
    MarkDownRx = re.compile(r".*\.(md)(|\.gz)?$")
    GETResult = namedtuple("GETResult", ["gzipped", "fspath"])

    def __init__(self, *args, **kwargs):
        self.matched_paths = dict()
        super().__init__(*args, **kwargs)


    def __default_dir_response(self, req_path):
        try:
            hit = self.matched_paths[req_path]
        except KeyError:
            results = (MDIndexRx.search(f),f for f in os.listdir(req_path))
            matches = (r,f for r,f in results if r)
            while True:
                try:
                    match, f = next(matches)
                except StopIteration:
                    raise JustDelegate("No markdown index found")
                lc_groups = [g.lower() for g in match.groups]
                if "md" in lc_groups:
                    break
            is_gz = ".gz" in lc_groups
            hit = GETResult(gzipped=is_gz, fspath=os.path.abspath(f))
            self.matched_paths[req_path] = hit
        return hit

    def __retrieve_markdown(self, req_path):
        try:
            hit = self.matched_paths[req_path]
        except KeyError:
            err = JustDelegate("Does not exist")
            m = MarkDownRx.search(req_path)
            if not m:
                raise err
            lc_groups = [s.lower() for s in m.groups()] 
            if not "md" in lc_groups:
                raise err
            is_gz = ".gz" in lc_groups
            hit = GETResult(gzipped=is_gz, fspath=req_path)
            self.matched_paths[req_path] = hit
        return hit

    def __answer_GET_HEAD(self, result, head=false):
        stream = None
        ack_gz = False
        self.send_response(200)
        # text/markdown is recent RFC7763;
        # .md renderer extensions should otherwise work with text/{plain,x-markdown}
        self.send_header("Content-Type", "text/markdown")
        # Prep response header
        if result.gzipped:
            ack_encode = self.headers.get("Accept-Encoding", "") 
            ack_encode = ack_encode.split(",") if ack_encode else []
            ack_gz = "gzip" in ack_encode
            if ack_gz:
                self.send_header("Content-Encoding", "gzip")
            else:
                stream = gzip.open(result.fspath, "rb")
        if stream is None:
            stream = open(result.fspath, "rb")
        length = response_length(stream, eval_eof=!ack_gz)
        stream.seek(0, os.SEEK_SET)
        self.send_header("Content-Length", str(length))
        self.end_headers()
        if head:
            return
        # Send file (cf. SimpleHTTPServer.py)
        self.copyfile(stream, self.wfile)


    def __find_markdown(self):
        requested_path = sanitize_path(self.request)
        msg = "Not Found"
        if os.path.exists(requested_path):
            if os.path.isdir(requested_path):
                if self.request[-1] == "/":
                    # Otherwise, let default handler answer 301
                    return self.__default_dir_response(requested_path)

                msg = "Do Redirect"
            else:
                return self.__retrieve_markdown(requested_path)
        raise JustDelegate(msg)

    def do_HEAD(self):
        try:
            hit = self.__find_markdown()
        except JustDelegate:
            return super().do_HEAD()
        return self.__answer_GET_HEAD(hit, head=True)

    def do_GET(self):
        try:
            hit = self.__find_markdown()
        except JustDelegate:
            return super().do_GET()
        return self.__answer_GET_HEAD(hit)


if __name__ == "__main__":
    with SimpleHTTPRequestHandler('127.0.0.1', Port) as myserv:
