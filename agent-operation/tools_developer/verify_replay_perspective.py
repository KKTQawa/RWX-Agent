"""静态检查回放里的视角与终局块，不需要启动 Java。

用法：python agent-operation/tools_developer/verify_replay_perspective.py [回放路径或目录 ...]
缺省检查 `replays/Hardup-v*.replay`。逐行输出「视角席位、录制终局、文件哈希」；
没有 `rwxPerspective`/`rwxOutcome` 的旧回放会显示 none——播放端对它们走原版逻辑。

真正播放并验证逐帧一致要用引擎：`java -cp desktop/build/headless/lib/* io.github.rwx.DesktopMain
--no-steam --replay-check=<replay>`，报告写在回放旁的 `<replay>.check.json`。
"""
import hashlib
import pathlib
import struct
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "evaluate" / "utils"))
import replay_map  # noqa: E402


def describe(path: pathlib.Path) -> str:
    raw = path.read_bytes()
    _, blocks = replay_map._read_container(raw)
    found = dict(blocks)
    if "rwxPerspective" not in found:
        seat, outcome = "none", "none"
    else:
        seat = struct.unpack(">i", found["rwxPerspective"])[0] + 1
        payload = found["rwxOutcome"]
        outcome = payload[2:2 + struct.unpack(">H", payload[:2])[0]].decode("utf-8")
    return (f"{path.name} seat={seat} outcome={outcome} "
            f"sha={hashlib.sha256(raw).hexdigest()[:12]} bytes={len(raw)}")


def main(argv: list[str]) -> int:
    targets = [pathlib.Path(a) for a in argv[1:]] or [ROOT / "replays"]
    files = sorted(p for target in targets
                   for p in ([target] if target.is_file() else target.glob("Hardup-v*.replay")))
    if not files:
        print("没有找到回放文件")
        return 1
    for path in files:
        print(describe(path))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
