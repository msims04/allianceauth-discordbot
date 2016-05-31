# The MIT License (MIT)
#
# Copyright (c) 2016 msims04
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
#
# ==========
#
# About
#
# This bot is used to set all user nicknames to '[Corporation Ticker] Character Name'.
#
# ==========
#
# Requirements
#
# git
# python 3.5.1
#
# python packages:
#   configobj
#   discord.py
#   mysql.connector
#
#   python3 -m pip install --upgrade configobj
#   python3 -m pip install --upgrade git+https://github.com/Rapptz/discord.py@async
#   python3 -m pip install --upgrade https://cdn.mysql.com/Downloads/Connector-Python/mysql-connector-python-1.0.12.tar.gz
#
# ==========
#
# Configuration
#
# Copy config.ini.example to config.ini and edit the values.
#
# ==========
#
# Running
#
# python3 bot.py --config config.ini > /dev/null 2>&1
#

import argparse
import asyncio
import configobj
import discord
import logging
import mysql.connector
import os
import sys

# Create the logger.
logger_handler = logging.StreamHandler()
logger_handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))

logger = logging.getLogger("allianceauth-discordbot")
logger.setLevel(logging.DEBUG)
logger.addHandler(logger_handler)

# Parse command line arguments.
parser = argparse.ArgumentParser()

parser.add_argument("-c", "--config", dest = "config_path", default = "./config.ini", help = "The path to the configuration file.")

args = parser.parse_args()

# Validate the configuration file.
if not os.path.isfile(args.config_path):
	logger.critical("Failed to open the configuration file '%s'." % (args.config_path))
	sys.exit(1)

config = configobj.ConfigObj(args.config_path)

try:
	# TODO: Find out why bots cannot login using a token.
	config['bot_email']
	config['bot_password']

	config['db_host']
	config['db_username']
	config['db_password']
	config['db_database']

	config['api_command_delay']

except Exception as e:
	logger.critical("Failed to read the configuration value %s." % (e))
	logger.exception(e)
	sys.exit(1)

# Connect to the database.
db = None

try:
	db = mysql.connector.connect(
		host     = config['db_host'],
		user     = config['db_username'],
		password = config['db_password'],
		database = config['db_database'])

except Exception as e:
	logger.critical("Failed to connect to the database.")
	logger.exception(e)
	sys.exit(1)

# Create the discord client and event handlers.
client = discord.Client()
loop   = asyncio.get_event_loop()
queue  = asyncio.Queue()

# Handles changing a user's nickname.
async def update_member_nickname(member):
	try:
		# Don't update the bot's nickname.
		if member == client.user:
			return

		# Fetch user from the database.
		cursor = db.cursor()

		cursor.execute(
			'SELECT `corporation_ticker`, `character_name`'
			'FROM `authentication_authservicesinfo`'
			'JOIN `eveonline_evecharacter` ON `eveonline_evecharacter`.`character_id` = `authentication_authservicesinfo`.`main_char_id`'
			'WHERE `discord_uid` = %s'
			'LIMIT 1', [member.id])

		rows = cursor.fetchall()

		cursor.close()

		# No user was found.
		if len(rows) <= 0:
			nickname = "[%s] %s" % ("-----", member.name)
			# TODO: Kick the user instead?

		# A user was found.
		else:
			for (corporation_ticker, character_name) in rows:
				nickname = "[%s] %s" % (corporation_ticker, character_name)

		# Queue a nickname change if needed.
		if member.nick != nickname:
			logger.info("Queuing change_nickname: '%s' to '%s'" % (member.name, nickname))
			await queue.put((client.change_nickname, member, nickname))

	except Exception as e:
		logger.exception(e)

# Handles limiting the amount of commands sent to the server to avoid rate limiting.
async def discord_command_queue_task():
	await client.wait_until_ready()

	while not client.is_closed:
		items = await queue.get()

		try:
			func = items[0]
			args = items[1:]

			await func(*args)

		except Exception as e:
			logger.error(e)

		await asyncio.sleep(float(config['api_command_delay']))

# Runs periodically and updates every user's nickname.
async def update_nicknames_task():
	await client.wait_until_ready()

	while not client.is_closed:
		logger.info("Checking nicknames for all users...")

		for member in client.get_all_members():
			await update_member_nickname(member)

		await asyncio.sleep(60 * 5)

@client.async_event
async def on_ready():
	logger.info("Logged in as %s (%s)" % (client.user.name, client.user.id))

	logger.debug("Creating task 'discord_command_queue_task'.")
	loop.create_task(discord_command_queue_task())

	logger.debug("Creating task 'update_nicknames_task'.")
	loop.create_task(update_nicknames_task())

@client.async_event
async def on_member_update(before, after):
	logger.info("Checking nickname for user '%s'..." % (after))
	await update_member_nickname(after)

# Run the bot.
try:
	loop.run_until_complete(client.login(config['bot_email'], config['bot_password']))
	loop.run_until_complete(client.connect())

except KeyboardInterrupt:
	loop.run_until_complete(client.close())

except Exception as e:
	logger.exception(e)
	loop.run_until_complete(client.close())

finally:
	for task in asyncio.Task.all_tasks():
		task.cancel()

		try:
			loop.run_until_complete(task)

		except Exception:
			pass

	loop.close()
