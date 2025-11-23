from biomni_esqlabs_tools import registry


class DummyAgent:
    def __init__(self):
        self.registered = []

    def add_tool(self, func):
        self.registered.append(func.__name__)


def test_iter_esqlabs_tools_returns_callables():
    tools = list(registry.iter_esqlabs_tools())
    assert tools, "ESQlabs registry should expose at least one tool"
    assert all(callable(tool) for tool in tools)


def test_register_with_agent_records_tools():
    agent = DummyAgent()
    names = registry.register_with_agent(agent)
    assert names == agent.registered
    assert all(isinstance(name, str) for name in names)
