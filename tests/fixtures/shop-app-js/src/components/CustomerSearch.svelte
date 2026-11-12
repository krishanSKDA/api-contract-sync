<script>
  let q = '';
  let results = [];

  async function search() {
    const res = await fetch('/api/customers?q=' + encodeURIComponent(q));
    results = await res.json();
  }
</script>

<input bind:value={q} on:input={search} />
{#each results as c}<p>{c.fullName}</p>{/each}
