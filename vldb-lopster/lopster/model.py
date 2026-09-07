"""Faithful TensorFlow implementation of LoPSTER's latent operators."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
import time

import numpy as np


@dataclass
class ModelResult:
    repaired: np.ndarray
    unchanged: np.ndarray
    train_loss: float
    validation_loss: float
    cache_hit: bool
    tensorflow_version: str
    training_seconds: float
    inference_seconds: float


def _tensorflow():
    try:
        import tensorflow as tf
    except ImportError as error:
        raise RuntimeError(
            "LoPSTER requires TensorFlow; install requirements-macos.txt in Python 3.11"
        ) from error
    return tf


class LatentOperator:
    def __init__(self, rotations: int, latent_size: int):
        tf = _tensorflow()
        shift = np.zeros((rotations, rotations), dtype=np.float32)
        for index in range(rotations):
            shift[index, (index + 1) % rotations] = 1.0
        current = tf.eye(rotations, dtype=tf.float32)
        matrices = [current]
        shift_tensor = tf.convert_to_tensor(shift)
        for _ in range(rotations - 1):
            current = tf.matmul(shift_tensor, current)
            matrices.append(current)
        self.shift_matrices = tf.stack(matrices)
        self.n_rotations = rotations
        self.latent_size = latent_size

    def translate(self, vector, shift):
        tf = _tensorflow()
        shaped = tf.reshape(vector, (self.n_rotations, -1))
        return tf.reshape(tf.matmul(self.shift_matrices[shift], shaped), vector.shape)

    def inverse(self, vector, shift):
        tf = _tensorflow()
        shaped = tf.reshape(vector, (self.n_rotations, -1))
        return tf.reshape(
            tf.linalg.matmul(self.shift_matrices[shift], shaped, transpose_a=True), vector.shape)


def _build_models(column_count: int, latent: int):
    tf = _tensorflow()
    inputs = tf.keras.Input(shape=(column_count,))
    vectors = [tf.keras.layers.Dense(latent, use_bias=False, activation="linear")(inputs)
               for _ in range(column_count)]
    outputs = []
    for vector in vectors:
        hidden = tf.keras.layers.Dense(128, activation="tanh")(vector)
        outputs.append(tf.keras.layers.Dense(1)(hidden))
    encoder = tf.keras.Model(inputs=inputs, outputs=vectors, name="lopster_encoder")
    decoder = tf.keras.Model(inputs=vectors, outputs=outputs, name="lopster_decoder")
    reconstruction = tf.keras.layers.Concatenate()(outputs)
    autoencoder = tf.keras.Model(inputs=inputs, outputs=reconstruction, name="lopster")
    return encoder, decoder, autoencoder


def _synthetic_errors(tf, values, operators: int, missing_value: float):
    weights = tf.concat([tf.constant([4.0]), tf.fill([operators - 1], 2.0)], axis=0)
    choices = tf.random.categorical(tf.math.log([weights]), tf.size(values), dtype=tf.int32)
    choices = tf.reshape(choices, tf.shape(values))
    transformed = tf.identity(values)
    increment = 1.0 / (operators / 2.0)
    for index in range(operators - 1):
        step = (index + 1) * increment
        if 0.9 <= step <= 1.1:
            step = (index + 2) * increment
        transformed = tf.where(choices == index + 1, transformed * step, transformed)
    transformed = tf.where(choices == operators - 1, missing_value, transformed)
    return transformed, choices


def train_and_repair(train: np.ndarray, validation: np.ndarray, dirty: np.ndarray,
                     config: dict[str, Any], cache_dir: Path) -> ModelResult:
    tf = _tensorflow()
    tf.keras.utils.set_random_seed(config["seed"])
    try:
        tf.config.set_visible_devices([], "GPU")
    except (RuntimeError, ValueError):
        pass
    latent = config["latent_dimension"]
    operators = config["operators"]
    if latent % operators:
        raise ValueError("algorithm.latent_dimension must be divisible by algorithm.operators")
    encoder, decoder, autoencoder = _build_models(train.shape[1], latent)
    operator = LatentOperator(operators, latent)
    encoder_path = cache_dir / "encoder.weights.h5"
    decoder_path = cache_dir / "decoder.weights.h5"
    cache_hit = bool(config["reuse_model"] and encoder_path.is_file() and decoder_path.is_file())
    train_loss = 0.0
    validation_loss = 0.0
    training_started = time.monotonic()
    if cache_hit:
        encoder.load_weights(encoder_path)
        decoder.load_weights(decoder_path)
    else:
        optimizer = tf.keras.optimizers.Adam(
            learning_rate=config["learning_rate"], epsilon=1e-6)
        mse = tf.keras.losses.MeanSquaredError()
        dataset = tf.data.Dataset.from_tensor_slices(train).shuffle(
            len(train), seed=config["seed"], reshuffle_each_iteration=True
        ).batch(config["batch_size"])

        @tf.function
        def step(clean):
            with tf.GradientTape() as tape:
                dirty_a, shifts_a = _synthetic_errors(
                    tf, clean, operators, config["missing_value_replacement"])
                dirty_b, shifts_b = _synthetic_errors(
                    tf, clean, operators, config["missing_value_replacement"])
                latents = encoder(dirty_a, training=True)
                stacked = tf.transpose(tf.stack(latents), [1, 0, 2])
                differences = shifts_a - shifts_b

                def translate_row(inputs):
                    row, row_differences = inputs
                    columns = []
                    for column_index in range(train.shape[1]):
                        difference = row_differences[column_index]
                        vector = row[column_index]
                        columns.append(tf.cond(
                            difference > 0,
                            lambda v=vector, d=difference: operator.inverse(v, d),
                            lambda v=vector, d=difference: operator.translate(v, -d),
                        ))
                    return tf.stack(columns)

                shifted = tf.vectorized_map(translate_row, (stacked, differences))
                predictions = tf.concat(decoder(tf.unstack(shifted, axis=1), training=True), axis=1)
                loss = mse(dirty_b, predictions)
            gradients = tape.gradient(loss, autoencoder.trainable_weights)
            optimizer.apply_gradients(zip(gradients, autoencoder.trainable_weights))
            return loss

        for _ in range(config["epochs"]):
            losses = [float(step(batch).numpy()) for batch in dataset]
            train_loss = float(np.mean(losses)) if losses else 0.0
        if len(validation):
            predicted = autoencoder(validation, training=False).numpy()
            validation_loss = float(np.mean(np.square(validation - predicted)))
        cache_dir.mkdir(parents=True, exist_ok=True)
        encoder.save_weights(encoder_path)
        decoder.save_weights(decoder_path)

    training_seconds = 0.0 if cache_hit else time.monotonic() - training_started
    inference_started = time.monotonic()
    latent_vectors = encoder(dirty, training=False)
    per_rotation = []
    current = tf.transpose(tf.stack(latent_vectors), [1, 0, 2])
    for _ in range(operators):
        decoded = tf.concat(decoder(tf.unstack(current, axis=1), training=False), axis=1)
        per_rotation.append(decoded)
        shifted_rows = []
        for row in tf.unstack(current, axis=0):
            shifted_rows.append(tf.stack([operator.translate(vector, 1) for vector in tf.unstack(row)]))
        current = tf.stack(shifted_rows)
    rotations = (operators - 1) - tf.argmax(tf.stack(per_rotation), axis=0, output_type=tf.int32)
    source = tf.transpose(tf.stack(latent_vectors), [1, 0, 2])
    repaired_latents = []
    for row_index, row in enumerate(tf.unstack(source, axis=0)):
        repaired_latents.append(tf.stack([
            operator.inverse(vector, rotations[row_index, column_index])
            for column_index, vector in enumerate(tf.unstack(row))
        ]))
    decoded = tf.concat(
        decoder(tf.unstack(tf.stack(repaired_latents), axis=1), training=False), axis=1).numpy()
    unchanged = rotations.numpy() == 0
    repaired = np.where(unchanged, dirty, decoded)
    inference_seconds = time.monotonic() - inference_started
    return ModelResult(repaired, unchanged, train_loss, validation_loss, cache_hit,
                       tf.__version__, training_seconds, inference_seconds)
