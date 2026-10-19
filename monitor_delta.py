"""Shared incremental snapshots; unchanged rows never travel back to the Monitor."""
from threading import RLock

import pandas as pd


class MonitorDeltaCache:
    def __init__(self):
        self._lock = RLock()
        self._snapshots = {}

    def read(self, fetch, table, since, open_ids):
        # Serialize readers: a second Streamlit session reuses the first snapshot.
        with self._lock:
            key = (table, since, tuple(sorted(open_ids)))
            snapshot = self._snapshots.get(key, {})
            known = {k: v['hash'] for k, v in snapshot.items()}
            delta = fetch('rpc/monitor_web_delta', {
                'p_table': table, 'p_since': since,
                'p_known': known, 'p_open_ids': list(open_ids),
            })
            if not isinstance(delta, dict) or not isinstance(delta.get('changed'), list) or not isinstance(delta.get('removed'), list):
                raise RuntimeError('Resposta incremental inválida; a base anterior foi preservada.')
            # Commit only after a complete, valid response. Failed requests retain prior state.
            updated = snapshot.copy()
            for removed in delta['removed']:
                updated.pop(removed, None)
            for changed in delta['changed']:
                updated[changed['key']] = {'hash': changed['hash'], 'row': changed['row']}
            self._snapshots[key] = updated
            # Bound memory across month transitions without dropping the other table.
            self._snapshots = {k: v for k, v in self._snapshots.items() if k[1] == since}
            frame = pd.DataFrame([v['row'] for v in updated.values()])
            frame.attrs['sincronizado_em'] = delta.get('sincronizado_em')
            return frame
