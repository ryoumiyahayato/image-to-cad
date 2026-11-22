"""Portable producer references; contained-path verification stays separate."""

from os.path import relpath as _host_relative_path


def relative_evidence_path(path, root):
    """Serialize a producer-owned relative path using the evidence protocol.

    Native file I/O still uses the host's Path implementation. JSON evidence
    uses forward slashes on every host, including sibling-stage ``..`` roots.
    This does not sanitize external input or authorize paths outside the job;
    the existing raw-artifact verifier performs those independent checks.
    """
    return _host_relative_path(path, root).replace("\\", "/")
