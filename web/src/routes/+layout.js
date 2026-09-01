import snapshot from '$lib/data/snapshot.json';

export const prerender = true;

export function load() {
	return {
		generatedAt: snapshot.generated_at,
		gitSha: snapshot.git_sha,
		tick: snapshot.tick,
		counts: snapshot.counts
	};
}
