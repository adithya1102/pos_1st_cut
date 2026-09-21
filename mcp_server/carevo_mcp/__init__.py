"""CareVo MCP server package.

Deliberately imports nothing. Re-exporting `server.mcp` here would make
`python -m carevo_mcp.server` import the module twice — once as a package
attribute, once as __main__ — which Python warns about and which would give
the decorator two chances to register the same tool.
"""
