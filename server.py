# Copyright(c) SimpleStaking, Viable Systems and Tezedge Contributors
# SPDX-License-Identifier: MIT
import os
import sys
import asyncio
import logging
from pathlib import Path
from shutil import rmtree, copytree
from time import sleep
from psutil import process_iter
from quart import Quart

app = Quart(__name__)
logger = logging.getLogger('fuzz log')
logger.setLevel(logging.INFO)
logger.addHandler(logging.StreamHandler(sys.stdout))

node_running = False


async def run(cmd, cwd):
    return await asyncio.create_subprocess_shell(
        cmd,
        stderr=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        cwd=cwd,
        shell=True
    )


async def read_lines(proc, stderr=True):
    stream = {True: proc.stderr, False: proc.stdout}[stderr]

    while True:
        line = await stream.readline()

        if not line:
            break

        yield line.decode('utf-8')[:-1]

    await proc.wait()


async def run_node_task():
    global node_running

    async for line in read_lines(await run('git pull --rebase', cwd='/tezedge')):
        logger.info(f'[GIT] {line}')

    cmd = (
        'KEEP_DATA=1 '
        './run.sh release '
        '--network=mainnet '
        '--tezos-data-dir /data '
        '--bootstrap-db-path /data/bootstrap_db'
    )

    async for line in read_lines(await run(cmd, cwd='/tezedge')):
        # use this message to make sure we are past PoW generation
        if node_running is False and 'Peer Handshaking successful' in line:
            node_running = True

        logger.info(f'[NODE] {line}')


async def run_fuzzer_task():
    global node_running

    async for line in read_lines(await run('git pull --rebase', cwd='/tezedge_fuzz')):
        logger.info(f'[GIT] {line}')

    while node_running is False:
        # don't start fuzzing until the node is up
        await asyncio.sleep(1)

    cmd = (
        'STATE_RESET_COUNT=10000 '
        'cargo fuzzcheck --test action_fuzz test_all'
    )

    async for line in read_lines(
            await run(cmd, cwd='/tezedge_fuzz/shell_automaton'),
            stderr=False):
        """
        TODO: detect when fuzzer is not making futher progress after a while
        and and restart it. The new fuzzer instance will pick a differnt state
        from the running node.
        """
        logger.info(f'[FUZZ] {line}')

    # at this point fuzzcheck has stopped, so generate the coverage report
    logger.info(f'[+++] Fuzzer stopped. Generating coverage report...')
    cmd = 'python /report.py'

    async for line in read_lines(await run(cmd, cwd='/tezedge_fuzz/shell_automaton')):
        logger.info(f'[REPORT] {line}')

    path = Path('/coverage/develop/.fuzzing.latest/action_fuzzer/')
    path.mkdir(parents=True, exist_ok=True)
    rmtree(f'{path}', ignore_errors=True)
    copytree('/tezedge_fuzz/shell_automaton/fuzz/reports/', f'{path}')


@app.route("/start")
async def start():
    global node_running
    node_running = False
    response = ''

    for proc in process_iter(['pid', 'name']):
        if proc.name() == 'light-node' or proc.name().startswith('action_fuzz'):
            response += f'<p>SIGTERM: {proc.name()} ({proc.pid})</p>'
            proc.terminate()

    response += f'<p>Running node...</p>'
    app.add_background_task(run_node_task)
    response += f'<p>Running fuzzer...</p>'
    app.add_background_task(run_fuzzer_task)
    return response


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('HTTP_PORT', 8080)))
