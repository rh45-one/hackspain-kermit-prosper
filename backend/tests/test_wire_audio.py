"""Measure wire energy and packet size, not only generated transcripts."""
import base64
import json
from types import SimpleNamespace

from pipecat.frames.frames import OutputAudioRawFrame

from agent.voice.context import CallContext
from agent.voice.pipeline import transport_params
from agent.voice.twilio import ProsperTwilioSerializer


async def test_twilio_wire_energy_and_native_packet_size(tmp_path):
    ctx = CallContext(data_dir=str(tmp_path))
    params = transport_params(ctx, SimpleNamespace(max_call_minutes=3))
    assert params.audio_out_10ms_chunks == 2
    serializer = ProsperTwilioSerializer(ctx)
    serializer._sample_rate = 8000
    for audio in [b'\xff' * 160, b'\x80' * 160]:
        frame = await serializer.deserialize(json.dumps({
            'event': 'media', 'media': {'payload': base64.b64encode(audio).decode()},
        }))
        assert frame.sample_rate == 8000
    stats = ctx.wire_audio['in_decoded']
    assert stats['packets'] == 2
    assert stats['samples'] == 320
    assert stats['energetic_packets'] == 1
    output = await serializer.serialize(OutputAudioRawFrame(
        audio=b'\x00\x10' * 160, sample_rate=8000, num_channels=1,
    ))
    assert len(base64.b64decode(json.loads(output)['media']['payload'])) == 160
    assert ctx.wire_audio['out_serialized']['energetic_packets'] == 1


def test_wire_counters_and_provisional_ids_are_per_socket(tmp_path):
    a, b = CallContext(data_dir=str(tmp_path)), CallContext(data_dir=str(tmp_path))
    assert a.call_id != b.call_id
    a.measure_wire_audio('in_decoded', b'\x00\x10' * 160)
    assert not b.wire_audio
