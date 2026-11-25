function roomTemperaturesHtml(summary) {
  const rooms = summary.room_temperatures || [];
  const escapeRoomText = (value) => {
    const element = document.createElement("span");
    element.textContent = String(value);
    return element.innerHTML;
  };
  const number = (value) => Number(value).toLocaleString([], {
    minimumFractionDigits: 1, maximumFractionDigits: 1,
  });
  const average = summary.temperature?.current;
  const count = summary.temperature?.aggregation_count || 0;
  return `
    <section class="room-temperatures" aria-label="Room temperatures">
      <h4>Room temperatures</h4>
      <ul>${rooms.map(room => `
        <li>
          <span>${escapeRoomText(room.label)}${room.source_count > 1 ? ` <small>(${room.source_count} sensors)</small>` : ""}</span>
          <strong>${room.current == null ? "No reading" : `${number(room.current)} °C`}</strong>
        </li>`).join("") || "<li>No rooms registered</li>"}</ul>
      <p class="room-average">Average of measured rooms:
        <strong>${average == null ? "--" : `${number(average)} °C`}</strong>
        · ${count} room${count === 1 ? "" : "s"}
      </p>
      <p class="room-average-note">Equal weight per room; sensor values are averaged within each room. Rooms without readings and unassigned sensors are excluded.</p>
    </section>`;
}
