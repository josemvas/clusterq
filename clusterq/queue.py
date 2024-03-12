import os
import re
import sys
from subprocess import Popen, PIPE
from .shared import config

def submitjob(jobscript):
    with open(jobscript, 'r') as fh:
        process = Popen(config.sbmtcmd, stdin=fh, stdout=PIPE, stderr=PIPE, close_fds=True)
    output, error = process.communicate()
    output = output.decode(sys.stdout.encoding).strip()
    error = error.decode(sys.stdout.encoding).strip()
    if process.returncode == 0:
        return re.fullmatch(config.sbmtregex, output).group(1)
    else:
        raise RuntimeError(error)
        
def getjobstate(jobid):
    process = Popen(config.statcmd + [jobid], stdout=PIPE, stderr=PIPE, close_fds=True)
    output, error = process.communicate()
    output = output.decode(sys.stdout.encoding).strip()
    error = error.decode(sys.stdout.encoding).strip()
    if process.returncode == 0:
        if not output:
            return True, None
        match = re.fullmatch(config.statregex, output)
        if match is None:
            return False, f'El trabajo $jobname no se envió porque no se pudo determinar su estado:\n{output}'
        if match.group(1) in config.finished_states:
            return True, None
        elif match.group(1) in config.running_states:
            return False, 'El trabajo $jobname no se envió porque hay un trabajo corriendo en el mismo directorio con el mismo nombre'
        else:
            return False, f'El trabajo $jobname no se envió porque su estado no está registrado: {match.group(1)}'
    else:
        for regex in config.ignored_errors:
            if re.fullmatch(regex, error):
                return True, None
        return False, f'El trabajo $jobname no se envió porque ocurrió un error al consultar su estado:\n{error}'