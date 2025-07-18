"""HuggingFace Generator Mixin."""

from typing import TYPE_CHECKING, Any, Protocol, Union, runtime_checkable

import torch
import torch.nn.functional as F

if TYPE_CHECKING:  # pragma: no cover
    from peft import PeftModel
    from transformers import PreTrainedModel
    from transformers.generation.utils import GenerationConfig

from fed_rag.data_structures import Context, Prompt, Query
from fed_rag.exceptions.generator import GeneratorError
from fed_rag.tokenizers.hf_pretrained_tokenizer import HFPretrainedTokenizer


@runtime_checkable
class HFGeneratorProtocol(Protocol):
    prompt_template: str
    tokenizer: HFPretrainedTokenizer
    model: Union["PreTrainedModel", "PeftModel"]
    generation_config: "GenerationConfig"

    def complete(
        self, prompt: str | list[str] | Prompt | list[Prompt], **kwargs: Any
    ) -> str | list[str]:
        pass  # pragma: no cover


class HuggingFaceGeneratorMixin:
    # complete
    def complete(
        self: HFGeneratorProtocol,
        prompt: str | list[str] | Prompt | list[Prompt],
        **kwargs: Any,
    ) -> str | list[str]:
        # convert to str | list[str]
        prompt = (
            [str(p) for p in prompt]
            if isinstance(prompt, list)
            else str(prompt)
        )

        # encode query
        tokenizer_result = self.tokenizer.unwrapped(
            prompt, return_tensors="pt"
        )
        inputs: torch.Tensor = tokenizer_result.input_ids
        inputs = inputs.to(self.model.device)

        # generate
        generated_ids = self.model.generate(
            inputs=inputs,
            generation_config=self.generation_config,
            tokenizer=self.tokenizer.unwrapped,
            **kwargs,
        )

        # skip the input tokens
        generated_ids = generated_ids[:, inputs.shape[-1] :]

        # decode tokens
        outputs: list[str] = self.tokenizer.unwrapped.batch_decode(
            generated_ids, skip_special_tokens=True
        )
        return outputs if len(outputs) > 1 else outputs[0]

    # generate
    def generate(
        self: HFGeneratorProtocol,
        query: str | list[str] | Query | list[Query],
        context: str | list[str] | Context | list[Context],
        **kwargs: Any,
    ) -> str | list[str]:
        """Implements generate method."""
        # convert query and context to list[str]
        query = (
            [str(q) for q in query]
            if isinstance(query, list)
            else [str(query)]
        )
        context = (
            [str(c) for c in context]
            if isinstance(context, list)
            else [str(context)]
        )

        if len(query) != len(context):
            raise GeneratorError(
                "There should be one context for every query."
            )

        formatted_queries = [
            self.prompt_template.format(query=q, context=c)
            for q, c in zip(query, context)
        ]
        return self.complete(prompt=formatted_queries, **kwargs)

    def compute_target_sequence_proba(
        self: HFGeneratorProtocol, prompt: str | Prompt, target: str
    ) -> torch.Tensor:
        """Computes the target sequence probability given the prompt.

        Args:
            generator (BaseGenerator): The generator LLM
            prompt (str | Prompt): The input i.e. conditional prompt sequence
            target (str): The target sequence

        Returns:
            proba (torch.Tensor): The probability of target sequence given a prompt.
                i.e., P_{LLM}(target | prompt)
        """
        if isinstance(prompt, Prompt):
            prompt = str(prompt)
        input_text = prompt + target
        encode_result = self.tokenizer.encode(input_text)
        input_ids = encode_result["input_ids"]

        # Get the token IDs for just the target portion
        prompt_only_encode_result = self.tokenizer.encode(prompt)
        target_start_idx = len(prompt_only_encode_result["input_ids"])
        target_ids = input_ids[target_start_idx:]

        # Create tensor and send to the device where the model resides
        input_ids_tensor = (
            torch.tensor(input_ids).unsqueeze(0).to(self.model.device)
        )

        # Get the logits from the model
        with torch.no_grad():
            outputs = self.model(input_ids_tensor)
            logits = outputs.logits

        # Calculate probability of each target token given the previous tokens
        log_probs = []
        for i, target_id in enumerate(target_ids):
            # get log prob of next target token in the sequence
            next_token_pos = target_start_idx + i
            next_token_logits = logits[0, next_token_pos, :]
            probs = F.softmax(next_token_logits, dim=-1)
            log_prob = torch.log(probs[target_id]).item()
            log_probs.append(log_prob)

        # Sum log probabilities to get sequence log probability
        sequence_log_prob = sum(log_probs)
        # Convert to probability
        sequence_prob = torch.exp(torch.tensor(sequence_log_prob))

        return sequence_prob
