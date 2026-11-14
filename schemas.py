"""HTTP envelopes; precise domain validation stays in the calculation engine."""
from pydantic import BaseModel, ConfigDict, StrictFloat, model_validator


class AnalyzeRequest(BaseModel):
    """Accept one source so requests cannot silently ignore competing recipe inputs."""
    model_config = ConfigDict(extra="forbid")
    dish: str | None = None
    custom_recipe: dict | None = None
    recipe_id: str | None = None

    @model_validator(mode="after")
    def one_source(self):
        """Require one recipe source for consistent routing."""
        if (self.dish is not None) + (self.custom_recipe is not None) + (self.recipe_id is not None) != 1:
            raise ValueError("Provide exactly one of dish, custom_recipe and recipe_id.")
        return self


class ReformulateRequest(AnalyzeRequest):
    """Accept v2 edits and the legacy goal fields without renaming existing inputs."""
    modifications: list[dict] | None = None
    options: dict | None = None
    goal: str | None = None
    reduce_percent: StrictFloat | None = None


class ParseRecipeRequest(BaseModel):
    """Accept plain recipe lines for a local preview before analyzing them."""
    model_config = ConfigDict(extra="forbid")
    text: str
    servings: StrictFloat = 1
