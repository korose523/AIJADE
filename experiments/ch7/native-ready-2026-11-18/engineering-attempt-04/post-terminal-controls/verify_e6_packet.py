"""Read-only verification of an already completed packet; no live data capture."""
import argparse
import json
from packet_common import verify_packet

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--packet',required=True)
    args=parser.parse_args()
    print(json.dumps(verify_packet(args.packet),indent=2))
