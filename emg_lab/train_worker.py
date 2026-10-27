import json
import sys
import traceback
from .storage import read_json
from .training import train


def emit(**event):
    print(json.dumps(event,ensure_ascii=False),flush=True)


if __name__ == '__main__':
    try:
        train(read_json(sys.argv[1]),emit)
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        emit(type='error',message=str(exc))
        sys.exit(1)
