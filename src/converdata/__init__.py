"""ConverData — Enterprise Data Discovery Agent.

Capas (PRD §8):
- ``models``, ``catalog``, ``memory``, ``identity``, ``discovery``, ``audit``: Python puro, sin LangGraph.
- ``llm``: única capa que importa LangChain (``langchain-aws``), carga perezosa.
- ``flows``: única capa que importa LangGraph.
"""

__version__ = "0.1.0"
