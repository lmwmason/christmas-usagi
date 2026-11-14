"""Independent, bounded storage for explicitly shared completed performances."""
from pathlib import Path
from threading import RLock
import copy
import json
import re
import shutil
import time
import uuid

from fastapi import HTTPException

SHARE_DAYS = 30
SHARE_BUDGET = 2 * 1024**3
MEDIA = {'mix': 'usagi-christmas-preview.mp3', 'voice': 'usagi-vocals-playback.mp3', 'backing': 'christmas-backing.mp3'}


class ShareStore:
    def __init__(self, directory):
        self.directory = Path(directory) / 'shares'
        self.directory.mkdir(parents=True, exist_ok=True)
        self.lock = RLock()
        self.cleanup()

    def cleanup(self):
        with self.lock:
            for path in self.directory.glob('*/share.json'):
                try:
                    if json.loads(path.read_text())['expires_at'] <= time.time():
                        shutil.rmtree(path.parent)
                except (OSError, ValueError, KeyError):
                    continue

    @staticmethod
    def public(data):
        return {key: data[key] for key in ('id', 'created_at', 'expires_at', 'result')}

    def create(self, job):
        with self.lock:
            snapshot = job.snapshot()
            if snapshot['status'] != 'completed':
                raise HTTPException(409, '공연 준비가 끝나면 공유할 수 있어요.')
            self.cleanup()
            for path in self.directory.glob('*/share.json'):
                data = json.loads(path.read_text())
                if data.get('sourceJobId') == job.id:
                    return self.public(data)
            audio = [job.directory / name for name in MEDIA.values()]
            if not all(path.is_file() for path in audio):
                raise HTTPException(410, '원본 공연이 만료되었어요. 다시 만든 뒤 공유해 주세요.')
            used = sum(p.stat().st_size for p in self.directory.rglob('*') if p.is_file())
            result = copy.deepcopy(snapshot['result'])
            result.pop('jobId', None)
            identifier = uuid.uuid4().hex
            result['backing'].update(file=f'/api/shares/{identifier}/audio/backing', mixFile=f'/api/shares/{identifier}/audio/mix', voiceFile=f'/api/shares/{identifier}/audio/voice')
            now = time.time()
            data = dict(id=identifier, created_at=now, expires_at=now+SHARE_DAYS*86400, sourceJobId=job.id, result=result)
            serialized = json.dumps(data, ensure_ascii=False)
            if used + sum(p.stat().st_size for p in audio) + len(serialized.encode()) > SHARE_BUDGET:
                raise HTTPException(507, '공유 보관함이 가득 찼어요. 음원을 내려받거나 나중에 다시 공유해 주세요.')
            target = self.directory / identifier
            temporary = self.directory / ('.' + identifier + '.tmp')
            try:
                temporary.mkdir()
                for path in audio:
                    shutil.copyfile(path, temporary / path.name)
                (temporary / 'share.json').write_text(serialized)
                temporary.replace(target)
            finally:
                if temporary.exists():shutil.rmtree(temporary)
            return self.public(data)

    def get(self, identifier):
        if not re.fullmatch(r'[a-f0-9]{32}', identifier):
            raise HTTPException(404, '공유 공연 링크를 확인해 주세요.')
        with self.lock:
            path = self.directory / identifier / 'share.json'
            if not path.is_file():
                raise HTTPException(404, '공유 공연이 만료되었거나 존재하지 않아요.')
            data = json.loads(path.read_text())
            if data['expires_at'] <= time.time():
                shutil.rmtree(path.parent)
                raise HTTPException(410, '공유 공연의 30일 보관 기간이 끝났어요. 새 공연을 만들어 주세요.')
            return self.public(data)
