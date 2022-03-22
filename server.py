# Copyright(c) SimpleStaking, Viable Systems and Tezedge Contributors
# SPDX-License-Identifier: MIT
import os
import sys
import asyncio
import logging
from enum import Enum
from pathlib import Path
from shutil import rmtree, copytree
from psutil import process_iter
from quart import Quart, send_from_directory
from async_timeout import timeout

app = Quart(__name__)
logger = logging.getLogger('fuzz log')
logger.setLevel(logging.INFO)
logger.addHandler(logging.StreamHandler(sys.stdout))


class Status(Enum):
    NodeDown = 0
    Init = 1
    NodeUp = 2
    Fuzzing = 3


status = Status.NodeDown


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
    global status

    async for line in read_lines(await run('git pull --rebase', cwd='/tezedge')):
        logger.info(f'[GIT] {line}')

    cmd = (
        'KEEP_DATA=1 '
        './run.sh release '
        '--network=mainnet '
        '--tezos-data-dir /data '
        '--bootstrap-db-path /data/bootstrap_db'
    )

    node = await run(cmd, cwd='/tezedge')
    status = Status.Init

    async for line in read_lines(node):
        # use this message to make sure we are past PoW generation
        if status == Status.Init and 'Peer Handshaking successful' in line:
            status = Status.NodeUp

        logger.info(f'[NODE] {line}')

    status = Status.NodeDown


async def run_fuzzer_task():
    global status

    async for line in read_lines(await run('git pull --rebase', cwd='/tezedge_fuzz')):
        logger.info(f'[GIT] {line}')

    # don't start fuzzing until the node is up
    while status != Status.NodeUp:
        await asyncio.sleep(1)

    cmd = (
        'cargo update; '
        'STATE_RESET_COUNT=10000 '
        'cargo fuzzcheck --test action_fuzz test_all'
    )

    fuzzer = await run(cmd, cwd='/tezedge_fuzz/shell_automaton')

    async for line in read_lines(fuzzer, stderr=False):
        """
        TODO: detect when fuzzer is not making futher progress after a while
        and and restart it. The new fuzzer instance will pick a differnt state
        from the running node.
        """
        if status == Status.NodeUp and 'simplest_cov' in line:
            status = Status.Fuzzing

        logger.info(f'[FUZZ] {line}')

    # at this point fuzzcheck has stopped, so generate the coverage report
    logger.info(f'[FUZZ] Fuzzer stopped. Generating coverage report...')
    cmd = 'python /report.py'
    report = await run(cmd, cwd='/tezedge_fuzz/shell_automaton')

    async for line in read_lines(report):
        logger.info(f'[REPORT] {line}')

    path = Path('/coverage/develop/.fuzzing.latest/action_fuzzer/')
    path.mkdir(parents=True, exist_ok=True)
    rmtree(f'{path}', ignore_errors=True)
    copytree('/tezedge_fuzz/shell_automaton/fuzz/reports/', f'{path}')
    rmtree('/static/reports/', ignore_errors=True)
    copytree('/tezedge_fuzz/shell_automaton/fuzz/reports/', '/static/reports/')


async def wait_for_node_shutdown():
    global status

    while status != Status.NodeDown:
        await asyncio.sleep(1)


def get_node_proc():
    for proc in process_iter(['pid', 'name']):
        if proc.name() == 'light-node':
            return proc

    return None


def get_fuzzer_proc():
    for proc in process_iter(['pid', 'name']):
        if proc.name().startswith('action_fuzz'):
            return proc

    return None


def terminate(proc):
    if proc is not None:
        proc.terminate()
        return f'<p>SIGTERM: {proc.name()} ({proc.pid})</p>'
    else:
        return ''


@app.route("/start")
async def start():
    global status
    response = ''

    if status not in (Status.NodeDown, Status.Fuzzing):
        return '<p>Error: busy</p>'

    node_proc = get_node_proc()
    response += terminate(node_proc)
    response += terminate(get_fuzzer_proc())

    if node_proc is not None:
        response += f'<p>Waiting for node to shut-down...</p>'

        try:
            async with timeout(5.0) as cm:
                await wait_for_node_shutdown()

        except asyncio.TimeoutError:
            response += f'<p>Timeout, sending SIGKILL...</p>'
            node_proc.kill()
            response += f'<p>Removing lock files...</p>'
            Path('/data/context/index/lock').unlink()
            Path('/data/bootstrap_db/db/LOCK').unlink()

    response += f'<p>Running node...</p>'
    app.add_background_task(run_node_task)
    response += f'<p>Running fuzzer...</p>'
    app.add_background_task(run_fuzzer_task)
    return response


@app.route('/')
async def report():
    return await static_dir('index.html')


@app.route('/<path:path>')
async def static_dir(path):
    logger.info(f'[STATIC] {path}')

    if path.startswith('web-files/'):
        root = '/static/'
    else:
        root = '/static/reports/'

    return await send_from_directory(root, path)


if __name__ == '__main__':
    app.run(host='127.0.0.1', port=int(os.getenv('HTTP_PORT', 8080)))
