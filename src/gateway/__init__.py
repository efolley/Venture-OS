"""VentureOS API gateway: 1 front door for the web UI and the API.

It forwards every request to the VentureOS API and adds what the API itself does not have:
an optional API key, rate limits per client, request IDs, a body size limit, and clear errors
when the API is down. It imports no agent code.
"""

__version__ = "0.1.0"
