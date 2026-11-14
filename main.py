"""Desktop entry point; concrete service wiring lives in bootstrap."""
import sys
from emg_lab.bootstrap import main

if __name__ == '__main__':
    sys.exit(main())
