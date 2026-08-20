import numpy as np

from bitty.envelope import ENV_RATE_HZ, step_values

SAMPLE_RATE = 44100
SAMPLES_PER_STEP = int(SAMPLE_RATE / ENV_RATE_HZ)


def test_envelope_runs_at_sixty_steps_per_second():
    assert ENV_RATE_HZ == 60.0


def test_each_step_holds_for_one_sixtieth_of_a_second():
    values = step_values((15, 10, 5), SAMPLE_RATE, SAMPLE_RATE)
    assert values[0] == 15.0
    assert values[SAMPLES_PER_STEP - 1] == 15.0
    assert values[SAMPLES_PER_STEP] == 10.0
    assert values[2 * SAMPLES_PER_STEP] == 5.0


def test_the_last_step_sustains_for_the_rest_of_the_note():
    """Chip voices have no natural decay; a short envelope must not cut a long note."""
    values = step_values((15, 10, 5), SAMPLE_RATE, SAMPLE_RATE)
    assert values[-1] == 5.0
    assert np.all(values[3 * SAMPLES_PER_STEP:] == 5.0)


def test_an_empty_envelope_is_the_identity():
    values = step_values((), 1000, SAMPLE_RATE)
    assert np.array_equal(values, np.ones(1000))


def test_a_note_shorter_than_one_step_still_renders():
    values = step_values((15, 10), 10, SAMPLE_RATE)
    assert len(values) == 10
    assert np.all(values == 15.0)


def test_negative_steps_are_preserved_for_pitch_envelopes():
    values = step_values((-2, 0), SAMPLES_PER_STEP * 2, SAMPLE_RATE)
    assert values[0] == -2.0
    assert values[-1] == 0.0
