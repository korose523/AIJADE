# Exact function bytes extracted from full source SHA256 e918de7431e3f27af2e03017a2f504bf00d85a6a08bf05d7ba5fcd3e14291035; test-only fake lifecycle/time.
def _read_listeners(lifecycle):
    """macOS system connection enumeration may require root; lsof is bounded."""
    try:
        started = time.monotonic()
        result = lifecycle.run(['/usr/sbin/lsof', '-nP', '-iTCP:11434', '-sTCP:LISTEN', '-FpfPtTn'],
                                capture_output=True, timeout=0.5, check=False)
        if time.monotonic()-started > 0.5 or result.returncode != 0 or result.stderr or len(result.stdout) > MAX_API_BYTES:
            return {'state': 'UNKNOWN', 'code': 'LISTENER_ENUMERATION_UNKNOWN'}
        records, process_pid, current = [], None, None
        def flush():
            if current is not None: records.append(dict(current))
        for line in result.stdout.decode('ascii').splitlines():
            if not line: continue
            code, value = line[0], line[1:]
            if code == 'p':
                flush(); current = None; process_pid = int(value)
            elif code == 'f':
                flush(); current = {'pid': process_pid}
            elif current is not None and code in ('P', 't', 'n'):
                current[{'P': 'protocol', 't': 'family', 'n': 'endpoint'}[code]] = value
            elif current is not None and code == 'T' and value.startswith('ST='):
                current['socketState'] = value[3:]
        flush()
        return {'state': 'OBSERVED', 'records': records}
    except Exception as error:
        return {'state': 'UNKNOWN', 'code': 'LISTENER_READ_UNKNOWN', 'errorClass': type(error).__name__}
