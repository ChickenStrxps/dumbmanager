"""Source and frozen entry point, with explicit child-process modes."""
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'backend'))

def main():
    if '--host' in sys.argv:
        sys.argv.remove('--host')
        from app import main as host_main
        return host_main()
    if '--native' in sys.argv:
        sys.argv.remove('--native')
        from native import main as native_main
        return native_main()
    from launcher import main as launch_main
    return launch_main()
if __name__=='__main__':raise SystemExit(main())
