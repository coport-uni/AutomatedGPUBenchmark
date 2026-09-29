# Split a captured live-mode console (script -qec) into its redrawn frames and print one (M6 debugging).
import re
import sys

text = (
    open(sys.argv[1], encoding="utf-8", errors="replace")
    .read()
    .replace("\r", "")
)
frames = re.split(r"\x1b\[\d+F\x1b\[J", text)
print("frames:", len(frames))
index = int(sys.argv[2]) if len(sys.argv) > 2 else len(frames) // 2
print(re.sub(r"\x1b\[[0-9;]*m", "", frames[index]))
