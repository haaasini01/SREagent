from mcp.server.fastmcp import FastMCP

from app.tools import check_db_status, fetch_service_logs, restart_resource

mcp = FastMCP("SRE-Agent-Simulated-Tools")

mcp.tool()(fetch_service_logs)
mcp.tool()(check_db_status)
mcp.tool()(restart_resource)


if __name__ == "__main__":
    mcp.run()
