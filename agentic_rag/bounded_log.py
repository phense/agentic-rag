"""Finite diagnostic files; never use this retention policy for source evidence."""
from datetime import datetime
from logging.handlers import RotatingFileHandler
import logging
import threading

from .secrets import strip_secrets

_LOCK=threading.Lock()


class ByteHandler(RotatingFileHandler):
    def shouldRollover(self,record):
        if self.stream is None:self.stream=self._open()
        self.stream.seek(0,2)
        return self.stream.tell()+len((self.format(record)+'\n').encode('utf-8'))>self.maxBytes


def append(path,message,*,max_bytes=1048576,backups=3):
    # Process-local synchronization plus bounded records keeps file size finite
    # even with concurrent hook processes. Rotation races are diagnostic-only.
    with _LOCK:
        path.parent.mkdir(parents=True,exist_ok=True)
        handler=ByteHandler(path,maxBytes=max_bytes,backupCount=backups,encoding='utf-8')
        try:
            prefix=datetime.now().isoformat(timespec='seconds')+' '
            available=8192-len(prefix.encode('utf-8'))-1
            message=strip_secrets(str(message))[0].encode('utf-8')[:available].decode('utf-8',errors='ignore')
            record=logging.LogRecord('agentic-rag',logging.INFO,'',0,
                prefix+message,(),None)
            handler.emit(record)
        finally:handler.close()
