from abc import ABC, abstractmethod


class BaseTool(ABC):
    name: str
    description: str

    @abstractmethod
    def parameters_schema(self) -> dict:
        """Return JSON Schema for the tool's parameters."""

    @abstractmethod
    async def execute(self, **kwargs) -> str:
        """Run the tool and return a string result."""

    def to_openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters_schema(),
            },
        }
