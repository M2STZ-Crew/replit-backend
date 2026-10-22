const FORMAT = new Intl.DateTimeFormat('en-PH', {
  timeZone: 'Asia/Manila',
  dateStyle: 'medium',
  timeStyle: 'short',
});

export default function RecordedTime({ value }) {
  if (!value) return <>Not recorded</>;
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return <>Not recorded</>;
  return <time dateTime={date.toISOString()}>{FORMAT.format(date)} PHT</time>;
}
