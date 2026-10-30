// Node "Down Message" (Workflow B)  ·  Code node  ·  Mode: Run Once for All Items
// Filter guards against the Postgres node emitting an empty "success" item when no rows.
return $input.all()
  .filter(i => i.json.name)
  .map(i => ({
    json: {
      telegram_text:
        `🔴 <b>CRITICAL — ${i.json.name} stopped reporting</b>\n` +
        `No data for ${i.json.silent_s}s (last seen ${i.json.last_seen_at}).\n\n` +
        `<b>Possible:</b> server/container down, agent crashed, or network issue.\n` +
        `<b>Check:</b> docker ps -a | grep ${i.json.name}`,
    },
  }));
