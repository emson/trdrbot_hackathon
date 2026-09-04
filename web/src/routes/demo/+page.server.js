import snapshot from '$lib/data/snapshot.json';

export const prerender = true;

export function load() {
	const {
		cycles, funnel, coach, forecasts_resolved, calibration, account, counts,
		generated_at, positions, equity_curve, attribution, competence, book, tick
	} = snapshot;
	return {
		cycles, funnel, coach, forecasts: forecasts_resolved, calibration, account,
		counts, generatedAt: generated_at, positions, equityCurve: equity_curve,
		attribution, competence, book, tick
	};
}
