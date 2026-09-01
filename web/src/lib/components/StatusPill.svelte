<script>
	import { statusPillClass, titleCase } from '$lib/format.js';
	let { status = '', label = '' } = $props();
	let cls = $derived(statusPillClass(status));
</script>

<span class="pill {cls}">{label || titleCase(status)}</span>
