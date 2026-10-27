"""Preserve surplus per-channel Delsys samples across unequal SDK polling blocks."""
import numpy as np


class ChannelAligner:
    def __init__(self, channels, max_pending):
        self.pending = [np.empty(0,dtype=np.float32) for _ in range(channels)]
        self.max_pending = max_pending

    def push(self, rows):
        if len(rows)!=len(self.pending):
            raise ValueError('Delsys 通道数量变化。')
        for i,row in enumerate(rows):
            values = np.asarray(row,dtype=np.float32).reshape(-1)
            if not np.isfinite(values).all():
                raise ValueError('Delsys 信号包含无效值。')
            self.pending[i] = np.concatenate((self.pending[i],values))
        n = min(map(len,self.pending))
        if max(map(len,self.pending))-n > self.max_pending:
            raise ValueError('Delsys 通道积压超过 2 秒，请检查传感器。')
        if not n:
            return None
        result = np.stack([x[:n] for x in self.pending])
        self.pending = [x[n:] for x in self.pending]
        return result
