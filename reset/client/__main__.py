#!/usr/bin/python3

import argparse
import logging
#import logging.handlers
import sys
import termios
import traceback

import curio

from . import ProtocolUser, Client, Rules
from ..proto import commands_pb2 as commands, events_pb2 as events
from .. import util

async def main():
	ap = argparse.ArgumentParser()
	ap.add_argument("host")
	ap.add_argument("port", type=int)
	args = ap.parse_args()

	logging.getLogger().setLevel(logging.DEBUG)
	logging.getLogger().addHandler(logging.FileHandler("reset.client.log", mode='w'))

	rules = Rules()
	protocol = ProtocolUser(logging.getLogger("protocol"))
	client = Client(logging.getLogger("client"), args.host, args.port, rules, protocol)

	flags = termios.tcgetattr(1)
	try:
		await client.run()
	except BaseException:
		termios.tcsetattr(1, termios.TCSANOW, flags)
		#sys.stdout.write("\x1bc")
		logging.getLogger().exception("Client crashed.")


if __name__ == '__main__':
	curio.run(main(), with_monitor=True)
