# LangSmith Studio Quick Launch

Simple checklist to spin up the visual LangGraph view for the expense bot.

1. ```bash
   cd /home/rodrigo/cuenta
   source lc-academy-env/bin/activate
   set -a; source .env; set +a      # loads LANGSMITH_* vars + PYTHONPATH
   export PYTHONPATH=src            # only needed if not already in .env
   langgraph dev
   ```
2. Wait for the CLI banner that shows the API + Studio URLs, then open the provided Studio link (for example `https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024`).
3. When finished, press `Ctrl+C` in the terminal to stop the dev server.

Studio reads the graph definition from `langgraph.json`, so keep that file in sync if paths change.
