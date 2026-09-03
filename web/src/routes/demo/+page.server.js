import snapshot from '$lib/data/snapshot.json';

export const prerender = true;

export function load() {
	const {
		cycles, funnel, coach, forecasts_resolved, calibration, account, counts,
		generated_at, positions
	} = snapshot;
	return {
		cycles, funnel, coach, forecasts: forecasts_resolved, calibration, account,
		counts, generatedAt: generated_at, positions
	};
}
