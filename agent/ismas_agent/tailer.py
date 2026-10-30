"""Follows a log file like `tail -F`: survives rotation and truncation.
Starts at the END of files that already exist (no replay of old history)."""
import os


class FileTailer:
    def __init__(self, path):
        self.path = path
        self.inode, self.pos = None, 0
        try:
            st = os.stat(path)
            self.inode, self.pos = st.st_ino, st.st_size
        except FileNotFoundError:
            pass

    def read_lines(self, max_bytes=1_000_000):
        try:
            st = os.stat(self.path)
        except FileNotFoundError:
            return []
        if st.st_ino != self.inode:          # new or rotated file -> read from start
            self.inode, self.pos = st.st_ino, 0
        elif st.st_size < self.pos:          # truncated
            self.pos = 0
        if st.st_size == self.pos:
            return []
        with open(self.path, "rb") as f:
            f.seek(self.pos)
            data = f.read(max_bytes)
        nl = data.rfind(b"\n")
        if nl == -1:                          # wait for a complete line
            return []
        chunk = data[: nl + 1]
        self.pos += len(chunk)
        return chunk.decode("utf-8", "replace").splitlines()
