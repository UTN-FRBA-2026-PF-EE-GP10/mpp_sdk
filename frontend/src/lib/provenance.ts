// See CURVE_SOURCES in mpp_sdk/curves/record.py. "hardware" is the normal
// case on this bench and stays quiet in the UI; anything else means the
// curve was not measured off a panel and must be obvious even in a
// cropped screenshot - the whole reason this field exists.

export interface ProvenanceInfo {
  measured: boolean
  label: string
}

const LABELS: Record<string, string> = {
  hardware: 'Measured',
  'firmware-replay': 'Replayed - not measured',
  simulated: 'Simulated - not measured',
  unknown: 'Provenance unknown - not confirmed measured',
}

export function provenanceInfo(source: string): ProvenanceInfo {
  return {
    measured: source === 'hardware',
    label: LABELS[source] ?? `${source} - not measured`,
  }
}
