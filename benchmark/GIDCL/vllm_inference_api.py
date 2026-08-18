"""Run GIDCL correction inference with an OpenAI-compatible API or vLLM.

OpenAI backend is portable default for CPU-only macOS hosts. Credentials
follow ZeroEC: OPENAI_API_KEY is required, OPENAI_API_BASE is optional, and
model is selected with GIDCL_MODEL.
"""

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import numpy as np
import pandas as pd
from sklearn.metrics import f1_score


SYSTEM_PROMPT = (
    "You are an expert data-cleaning assistant. Follow requested output "
    "format exactly and return only the answer."
)


def add_suffix_to_filename(file_path, suffix):
    path = Path(file_path)
    return str(path.with_name(f"{path.stem}_{suffix}{path.suffix}"))


def load_inputs(path, is_json):
    if is_json:
        frame = pd.read_json(path)
        return frame, frame["instruction"].astype(str).tolist()
    return None, np.load(path, allow_pickle=False).astype(str).tolist()


def openai_generate(prompts, max_tokens):
    try:
        from openai import OpenAI
    except ImportError as error:
        raise RuntimeError("OpenAI backend requires `pip install openai`.") from error

    try:
        api_key = os.environ["OPENAI_API_KEY"]
    except KeyError as error:
        raise RuntimeError(
            "OPENAI_API_KEY environment variable is not configured"
        ) from error

    base_url = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1")
    model = os.getenv("GIDCL_MODEL", "gpt-4o-mini")
    client = OpenAI(api_key=api_key, base_url=base_url)
    generated = []
    for prompt in prompts:
        response = client.chat.completions.create(
            model=model,
            temperature=0,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )
        generated.append(response.choices[0].message.content or "")
    return generated


def vllm_generate(prompts, args, max_tokens):
    try:
        from vllm import LLM, SamplingParams
    except ImportError as error:
        raise RuntimeError("vLLM backend requires vLLM on a supported host.") from error

    if not args.checkpoint_dir:
        raise ValueError("--checkpoint-dir is required for vLLM backend.")

    temporary_model = tempfile.mkdtemp(prefix="gidcl-model-")
    try:
        command = [
            sys.executable,
            "src/export_model.py",
            "--model_name_or_path", args.model_name_or_path,
            "--finetuning_type", "lora",
            "--checkpoint_dir", args.checkpoint_dir,
            "--output_dir", temporary_model,
            "--template", args.template,
        ]
        environment = os.environ.copy()
        environment["CUDA_VISIBLE_DEVICES"] = str(args.device)
        subprocess.run(command, check=True, env=environment)

        llm = LLM(model=temporary_model, tensor_parallel_size=1)
        sampling = SamplingParams(
            temperature=0, top_p=1, max_tokens=max_tokens, logprobs=1
        )
        chat_prompts = [
            "A chat between a curious user and an artificial intelligence "
            "assistant. USER: %s ASSISTANT:" % prompt
            for prompt in prompts
        ]
        return [item.outputs[0].text for item in llm.generate(chat_prompts, sampling)]
    finally:
        shutil.rmtree(temporary_model, ignore_errors=True)


def report_legacy_match_f1(frame):
    if "output" not in frame or "predict" not in frame:
        return
    truth = frame["output"].map(lambda value: 0 if value == "dismatch" else 1)
    prediction = frame["predict"].map(
        lambda value: 0 if value == "dismatch" else 1
    )
    print("legacy match F1:", f1_score(truth, prediction))


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-test_file", "--file", required=True)
    parser.add_argument("-json", "--json", action="store_true")
    parser.add_argument(
        "--backend", choices=("openai", "vllm"), default="openai",
        help="openai uses ZeroEC-style environment credentials",
    )
    parser.add_argument("-checkpoint_dir", "--checkpoint-dir")
    parser.add_argument("--device", "--count", dest="device", type=int, default=0)
    parser.add_argument("--model-name-or-path", default="vicuna-13b-1.3")
    parser.add_argument("--template", default="vicuna")
    parser.add_argument("--output")
    return parser


def main():
    args = build_parser().parse_args()
    frame, prompts = load_inputs(args.file, args.json)
    max_tokens = 512 if args.json else 16
    if args.backend == "openai":
        generated = openai_generate(prompts, max_tokens)
    else:
        generated = vllm_generate(prompts, args, max_tokens)

    if frame is not None:
        frame["predict"] = generated
        report_legacy_match_f1(frame)
        output = args.output or str(
            Path("inference") / f"{Path(args.file).stem}_output.csv"
        )
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        frame.to_csv(output, index=False)
    else:
        output = args.output or add_suffix_to_filename(args.file, "output")
        np.save(output, np.asarray(generated))
    print(output)


if __name__ == "__main__":
    main()
