"""Bounded Codex app-server runtime with durable, task-scoped feedback."""
import fcntl
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import time

import worker_mailbox as mailbox

ACTIVE = {'starting', 'running'}


def save_state(directory, state):
    state['updated_at'] = time.time()
    tmp = directory / 'status.tmp'
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2))
    tmp.replace(directory / 'status.json')


def stop_process(process):
    if process is None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()


class ProtocolError(Exception):
    pass


class DeliveryUnknown(Exception):
    pass


class Runtime:
    def __init__(self, directory, state):
        self.directory, self.state = directory, state
        self.process = None
        self.selector = selectors.DefaultSelector()
        self.buffer = b''
        self.serial = 0
        self.responses = {}
        self.active_turn = None
        self.turn_text = {}
        self.completed_turns = {}
        self.last_event = time.monotonic()
        self.started = self.last_event
        self.elapsed_before = state.get("runtime_total_seconds", 0)
        self.state["execution_started_at"] = time.time()
        self.deadline = self.started + state.get('max_seconds', 1800)
        self.stop_reason = None
        self.turn_status = None
        self.events = None
        self.inflight = {}
        self.last_finished = None

    def checkpoint(self):
        now = time.monotonic()
        if (self.directory / 'cancel.request').exists():
            self.stop_reason = 'cancelled'
            raise InterruptedError('cancelled')
        if now >= self.deadline:
            self.stop_reason = 'deadline_reached'
            raise InterruptedError('deadline_reached')
        self.state.update(elapsed_seconds=round(self.elapsed_before+now-self.started, 1),
                          quiet_seconds=round(now-self.last_event, 1),
                          needs_attention=now-self.last_event >= self.state.get('quiet_warning_seconds', 300))
        save_state(self.directory, self.state)

    def write(self, data):
        encoded = (json.dumps(data, ensure_ascii=False)+'\n').encode()
        self.process.stdin.write(encoded)
        self.process.stdin.flush()

    def request(self, method, params, timeout=90):
        self.serial += 1
        req_id = str(self.serial)
        self.write({'id': req_id, 'method': method, 'params': params})
        end = min(self.deadline, time.monotonic()+timeout)
        while req_id not in self.responses:
            self.checkpoint()
            if time.monotonic() >= end:
                raise DeliveryUnknown('Codex response timed out')
            self.pump(0.2)
        reply = self.responses.pop(req_id)
        if 'error' in reply:
            raise ProtocolError(str(reply['error'].get('message', 'Codex rejected request'))[:600])
        return reply.get('result', {})

    def event(self, event):
        self.events.write(json.dumps(event, ensure_ascii=False)+'\n')
        self.events.flush()
        self.last_event = time.monotonic()
        self.state['last_event'] = event.get('type')

    def notification(self, method, params):
        if params.get('threadId') not in {None, self.state.get('thread_id')}:
            return
        if method == 'turn/started':
            self.active_turn = params['turn']['id']
            self.turn_status = 'inProgress'
            self.state.pop('finished_at', None)
            self.state.update(status='running', phase='awaiting_model_or_output', active_turn_id=self.active_turn)
        elif method in {'item/started', 'item/completed'}:
            item = params.get('item') or {}
            kind = item.get('type')
            mapped = {'agentMessage':'agent_message', 'commandExecution':'command_execution',
                      'mcpToolCall':'mcp_tool_call', 'fileChange':'file_change'}.get(kind)
            if mapped:
                normalized = dict(item, type=mapped)
                if kind == 'commandExecution':
                    normalized['aggregated_output'] = item.get('aggregatedOutput')
                    normalized['exit_code'] = item.get('exitCode')
                normalized['status'] = {'inProgress':'in_progress'}.get(item.get('status'), item.get('status'))
                self.event({'type': method.replace('/', '.'), 'item': normalized})
            if method == 'item/completed' and kind == 'agentMessage':
                turn_id = params['turnId']
                self.turn_text.setdefault(turn_id, {})[item['id']] = item.get('text', '')
            if kind in {'commandExecution','mcpToolCall'}:
                self.state['phase'] = 'tool_running' if method.endswith('started') else 'awaiting_model_or_output'
        elif method == 'turn/completed':
            turn = params['turn']; turn_id = turn['id']
            self.turn_status = turn['status']
            result = '\n\n'.join(self.turn_text.get(turn_id, {}).values()).strip()
            success = turn['status'] == 'completed' and bool(result)
            self.completed_turns[turn_id] = (success, result)
            if result:
                results = self.directory / 'results'; results.mkdir(exist_ok=True)
                (results / (turn_id+'.txt')).write_text(result)
                (self.directory / 'result.txt').write_text(result)
            for mid, tid in list(self.inflight.items()):
                if tid == turn_id:
                    mailbox.update_message(self.directory, mid, status='replied' if success else 'failed',
                                           reply=result, replied_at=time.time(),
                                           error=None if success else 'Worker回合未成功完成')
                    del self.inflight[mid]
            if self.active_turn == turn_id:
                self.active_turn = None
            self.last_finished = time.monotonic()
            self.state.update(status='completed_unverified' if success else 'failed',
                              active_turn_id=None, phase='finished', finished_at=time.time(),
                              observed_failed_turn=not success)
            self.event({'type':'turn.completed' if success else 'turn.failed', 'turn_id':turn_id})
        elif method == 'thread/tokenUsage/updated':
            self.state['usage'] = params.get('tokenUsage')

    def pump(self, timeout=0.2):
        if self.process.poll() is not None:
            raise DeliveryUnknown('Codex process ended')
        if not self.selector.select(timeout):
            return
        chunk = os.read(self.process.stdout.fileno(), 65536)
        if not chunk:
            raise DeliveryUnknown('Codex connection closed')
        self.buffer += chunk
        while b'\n' in self.buffer:
            line, self.buffer = self.buffer.split(b'\n', 1)
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if not isinstance(event, dict):
                continue
            if 'id' in event and 'method' not in event:
                self.responses[str(event['id'])] = event
            elif 'id' in event:
                # Unattended workers cannot grant additional permissions or invent user answers.
                self.write({'id':event['id'], 'error':{'code':-32601,'message':'This worker cannot answer interactive permission requests; report the blocker.'}})
                self.state['interaction_blocker'] = 'Worker请求交互或权限，需要主Agent检查'
            elif event.get('method'):
                self.notification(event['method'], event.get('params') or {})

    def connect(self, resume):
        cfg = json.loads((self.directory / 'runtime.json').read_text())
        env = dict(os.environ, CODEX_HOME=str(self.directory/'home'))
        err = (self.directory/'stderr.log').open('a')
        self.process = subprocess.Popen([cfg['launcher'],'-c','agents.enabled=false','-c','features.plugins=false','app-server','--stdio'],
                         env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=err, start_new_session=True)
        err.close()
        self.selector.register(self.process.stdout, selectors.EVENT_READ)
        self.state.update(pid=self.process.pid, status='running', messaging_enabled=True, phase='connecting')
        self.state.pop('finished_at', None)
        self.request('initialize', {'clientInfo':{'name':'deepseek-worker','version':'2'},
                                   'capabilities':{'experimentalApi':True}})
        self.write({'method':'initialized','params':{}})
        params = {'cwd':self.state['cwd'], 'model':cfg['model'], 'modelProvider':'opencode_go',
                  'sandbox':'read-only' if self.state['role']=='review' else 'workspace-write', 'approvalPolicy':'never'}
        if resume:
            params['threadId'] = self.state['thread_id']
        result = self.request('thread/resume' if resume else 'thread/start', params)
        if result.get('model') != cfg['model'] or result.get('modelProvider') != 'opencode_go':
            raise ProtocolError('Unexpected model/provider; stopped')
        self.state.update(thread_id=result['thread']['id'], actual_model=result['model'],
                          actual_provider=result['modelProvider'], route_verified=True)
        if self.state.get('computer_use_enabled'):
            # Wait for the explicitly configured MCP before constructing the first model turn.
            inventory = self.request('mcpServerStatus/list', {'threadId': self.state['thread_id']}, timeout=120)
            cua = next((item for item in inventory.get('data', []) if item.get('name') == 'cua_repl'), {})
            if cua.get('runtimeStatus') != 'connected' or 'js' not in cua.get('tools', {}):
                raise ProtocolError('Configured Computer Use runtime is not connected')
            self.state['computer_use_ready'] = True
        if self.state.get('extra_mcp_servers'):
            inventory = self.request('mcpServerStatus/list', {'threadId': self.state['thread_id']}, timeout=120)
            connected = {item['name'] for item in inventory.get('data', []) if item.get('runtimeStatus') == 'connected'}
            if not set(self.state['extra_mcp_servers']).issubset(connected):
                raise ProtocolError('A task-selected MCP server is not connected')
        save_state(self.directory, self.state)

    def turn_params(self, inputs):
        # Keep filesystem isolation, but give workers the host's authorized network access.
        policy = {'type': 'readOnly' if self.state['role'] == 'review' else 'workspaceWrite',
                  'networkAccess': True}
        if self.state['role'] != 'review':
            policy['writableRoots'] = self.state.get('writable_roots', [self.state['cwd']])
        return {'threadId': self.state['thread_id'], 'input': inputs, 'sandboxPolicy': policy}

    def send_message(self, message):
        mid = message['id']
        marker = '[反馈 '+mid+']'
        text = marker+'\n用户对当前任务的补充：\n'+message['text']+'\n继续同一任务，保留原任务约束。请简短说明如何处理这条补充；不要把收到消息等同于已完成。'
        inputs = [{'type':'text','text':text}]
        image_path = (message.get('image') or {}).get('path')
        if image_path:
            resolved = Path(image_path).resolve()
            if not resolved.is_relative_to((self.directory/'messages').resolve()):
                mailbox.update_message(self.directory, mid, status='failed', error='图片引用无效')
                return
            inputs.append({'type':'localImage','path':str(resolved)})
        mailbox.update_message(self.directory, mid, status='sending', sending_at=time.time())
        try:
            if self.active_turn:
                expected = self.active_turn
                try:
                    result = self.request('turn/steer', {'threadId':self.state['thread_id'],
                                'expectedTurnId':expected,'input':inputs}, timeout=30)
                    tid = result['turnId']
                except ProtocolError as exc:
                    # Retry only after an authoritative completion changed the active turn.
                    if self.active_turn != expected:
                        mailbox.update_message(self.directory, mid, status='queued', error=None)
                        return
                    raise
            else:
                result = self.request('turn/start', self.turn_params(inputs), timeout=60)
                tid = result['turn']['id']
                if tid not in self.completed_turns:
                    self.active_turn = tid
            self.inflight[mid] = tid
            mailbox.update_message(self.directory, mid, status='delivered', delivered_at=time.time(), turn_id=tid, error=None)
            if tid in self.completed_turns:
                success, reply = self.completed_turns[tid]
                mailbox.update_message(self.directory, mid, status='replied' if success else 'failed',
                                       reply=reply, replied_at=time.time(), error=None if success else '回合失败')
                self.inflight.pop(mid, None)
            else:
                self.state.update(status='running', active_turn_id=tid)
        except ProtocolError as exc:
            mailbox.update_message(self.directory, mid, status='failed', error=str(exc))
        except (DeliveryUnknown, OSError):
            mailbox.update_message(self.directory, mid, status='uncertain', error='送达状态未知，请先检查回执，不要重复提交')
            raise

    def run(self, resume=False):
        self.events = (self.directory/'events.jsonl').open('a')
        try:
            self.connect(resume)
            # A crashed request can have reached Codex. Never silently send it twice.
            for message in mailbox.list_messages(self.directory):
                if message.get('status') in {'sending', 'delivered'}:
                    mailbox.update_message(self.directory,message['id'],status='uncertain',error='上次连接中断，未取得完成回执；不会自动重复执行')
            if not resume:
                prompt = (self.directory/'prompt.md').read_text()
                result = self.request('turn/start', self.turn_params([{'type':'text','text':prompt}]))
                tid = result['turn']['id']
                if tid not in self.completed_turns:
                    self.active_turn = tid
            while True:
                self.checkpoint()
                for message in mailbox.pending_messages(self.directory):
                    self.send_message(message)
                if not self.active_turn:
                    if self.last_finished is None:
                        self.last_finished = time.monotonic()
                    if time.monotonic()-self.last_finished > 2:
                        break
                self.pump()
        except (KeyboardInterrupt, InterruptedError):
            self.state.update(status=self.stop_reason or 'cancelled')
        except Exception as exc:
            self.state.update(status='failed', reason=type(exc).__name__)
            for message in mailbox.pending_messages(self.directory):
                mailbox.update_message(self.directory,message['id'],status='failed',error='运行连接失败，尚未送达')
        finally:
            stop_process(self.process)
            if self.process:
                self.process.stdin.close()
                self.process.stdout.close()
            for mid in self.inflight:
                mailbox.update_message(self.directory,mid,status='failed',error='任务已停止；此前已送达，未获得完成回执')
            for message in mailbox.list_messages(self.directory):
                if message.get('status') == 'sending':
                    mailbox.update_message(self.directory,message['id'],status='uncertain',error='连接已结束，送达状态未知')
                elif message.get('status') == 'queued' and self.state.get('status') != 'completed_unverified':
                    mailbox.update_message(self.directory,message['id'],status='failed',error='运行停止，尚未送达')
            self.state['runtime_total_seconds'] = round(self.elapsed_before + time.monotonic()-self.started, 1)
            self.state['elapsed_seconds'] = self.state['runtime_total_seconds']
            self.state.update(phase='finished', finished_at=time.time(), active_turn_id=None,
                              needs_attention=self.state.get('status')!='completed_unverified')
            save_state(self.directory,self.state)
            self.selector.close(); self.events.close()
        return self.state


def supervise(directory, state=None, resume=False):
    directory = Path(directory).resolve()
    with (directory/'runtime.lock').open('a') as lock:
        end = time.monotonic()+10 if resume else time.monotonic()+1
        while True:
            try:
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= end:
                    return None
                time.sleep(.2)
        if resume:
            state=json.loads((directory/'status.json').read_text())
            if not state.get('messaging_enabled') or state.get('status') in {'cancelled','deadline_reached'}:
                return state
            if state.get('status') in ACTIVE:
                # Free lock + running state means the prior supervisor exited abnormally.
                # Never race a possibly surviving Codex process or kill an unverified PID.
                for m in mailbox.list_messages(directory):
                    if m.get('status') in {'sending', 'delivered'}:
                        mailbox.update_message(directory,m['id'],status='uncertain',error='原监督进程异常结束，需要检查；不会重发')
                    elif m.get('status') == 'queued':
                        mailbox.update_message(directory,m['id'],status='failed',error='原执行进程状态未知，未启动重复会话')
                return state
            if not mailbox.pending_messages(directory):
                return state
            if not state.get('thread_id'):
                for m in mailbox.pending_messages(directory):
                    mailbox.update_message(directory,m['id'],status='failed',error='原会话尚未建立，不能接续')
                return state
        return Runtime(directory,state).run(resume)
