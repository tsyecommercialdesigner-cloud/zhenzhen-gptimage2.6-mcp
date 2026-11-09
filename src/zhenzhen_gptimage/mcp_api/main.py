"""Stdio entry point."""
import argparse
import asyncio
from pathlib import Path
from zhenzhen_gptimage.bootstrap.config import load_config
from zhenzhen_gptimage.bootstrap.observability import configure_logging
from .server import create_server
from .lifecycle import running_service

def main():
    parser=argparse.ArgumentParser(description='Local image generation MCP server')
    parser.add_argument('--config-dir',type=Path,default=Path.cwd())
    parser.add_argument('--env-file',type=Path)
    parser.add_argument('--data-dir',type=Path,default=Path.cwd()/'runtime-data')
    args=parser.parse_args()
    config=load_config(args.config_dir,args.data_dir,env_file=args.env_file)
    configure_logging()
    async def run():
        async with running_service(config) as backend:
            await create_server(backend).run_async(transport='stdio',show_banner=False)
    asyncio.run(run())

if __name__ == '__main__': main()
