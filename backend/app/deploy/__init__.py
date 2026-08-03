"""Build-time deployment provisioning scripts (Phase 4B).

Code here runs exactly once, during ``docker build`` of the public
deployment image -- never inside the running server process and never
in response to an HTTP request. It has no dependency on the rest of
``app`` beyond the standard library, so it never pulls the heavy
``mast``/``science``/``ml`` extras into the deployed image.
"""
