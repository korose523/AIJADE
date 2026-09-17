import type { MaybeRefOrGetter } from 'vue'

import { until } from '@vueuse/core'
import { BufferTarget, MediaStreamAudioTrackSource, Output, QUALITY_MEDIUM, WavOutputFormat } from 'mediabunny'
import { ref, shallowRef, toRef } from 'vue'

import { reportV9Perception } from '../../libs/v9-event-reporter'

export interface AudioRecorderPerceptionOptions {
  sessionId?: string
  originDevice?: string
  privacyLevel?: 0 | 1 | 2 | 3
  reportPerception?: typeof reportV9Perception
}

function getMediaStreamTrack(stream: MediaStream) {
  const tracks = stream.getAudioTracks()
  if (!tracks.length)
    throw new Error('No audio tracks found in stream')
  return tracks[0]
}

export function useAudioRecorder(
  media: MaybeRefOrGetter<MediaStream | undefined>,
  perception: AudioRecorderPerceptionOptions = {},
) {
  const mediaRef = toRef(media)
  const recording = shallowRef<Blob>()

  const mediaOutput = ref<Output>()
  const mediaFormat = ref<string>()

  const onStopRecordHooks = ref<Array<(recording: Blob | undefined) => Promise<void>>>([])
  const sessionId = perception.sessionId ?? globalThis.crypto?.randomUUID?.() ?? `audio-${Date.now()}`
  const report = perception.reportPerception ?? reportV9Perception

  function onStopRecord(callback: (recording: Blob | undefined) => Promise<void>) {
    onStopRecordHooks.value.push(callback)
    // Return unsubscribe function to prevent memory leaks
    return () => {
      onStopRecordHooks.value = onStopRecordHooks.value.filter(h => h !== callback)
    }
  }

  async function startRecord() {
    await until(mediaRef).toBeTruthy()

    const track = await getMediaStreamTrack(mediaRef.value!)
    mediaOutput.value = new Output({ format: new WavOutputFormat(), target: new BufferTarget() })

    const audioSource = new MediaStreamAudioTrackSource(track, { codec: 'pcm-f32', bitrate: QUALITY_MEDIUM })
    audioSource.errorPromise.catch(console.error)
    mediaOutput.value.addAudioTrack(audioSource)

    mediaFormat.value = await mediaOutput.value.getMimeType()
    await mediaOutput.value.start()
  }

  async function stopRecord() {
    if (!mediaOutput.value) {
      return
    }

    await mediaOutput.value.finalize()
    const bufferTarget = mediaOutput.value.target as BufferTarget | undefined
    const buffer = bufferTarget?.buffer
    const audioBlob = buffer ? new Blob([buffer], { type: mediaFormat.value }) : undefined

    recording.value = audioBlob

    // Only report recording metadata; raw microphone bytes never leave the client.
    if (audioBlob) {
      const timestamp = Date.now()
      const traceId = `${sessionId}:audio:${timestamp}`
      report({
        event_id: traceId,
        session_id: sessionId,
        trace_id: traceId,
        correlation_id: sessionId,
        timestamp,
        origin_device: perception.originDevice ?? 'stage-ui',
        privacy_level: perception.privacyLevel ?? 2,
        risk_score: 0,
        source: 'audio:microphone',
        content: JSON.stringify({
          mime_type: audioBlob.type,
          bytes: audioBlob.size,
        }),
        stimulus_features: { bytes: audioBlob.size },
      })
    }

    // await hooks and catch errors
    for (const hook of onStopRecordHooks.value) {
      try {
        await hook(audioBlob)
      }
      catch (err) {
        console.error('onStopRecord hook failed:', err)
      }
    }

    mediaOutput.value = undefined

    return audioBlob
  }

  return {
    startRecord,
    stopRecord,
    onStopRecord,

    recording,
  }
}
