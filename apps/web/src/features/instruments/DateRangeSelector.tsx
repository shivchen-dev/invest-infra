interface DateRangeSelectorProps {
  options: ReadonlyArray<number>;
  rangeDays: number;
  onRangeChange: (days: number) => void;
}

export function DateRangeSelector({
  options,
  rangeDays,
  onRangeChange,
}: DateRangeSelectorProps) {
  return (
    <div className="etfDetailRangeRow" role="group" aria-label="行情区间">
      {options.map((days) => {
        const selected = days === rangeDays;
        return (
          <button
            key={days}
            type="button"
            className={`etfDetailRangeButton${
              selected ? " etfDetailRangeButtonActive" : ""
            }`}
            aria-pressed={selected}
            onClick={() => onRangeChange(days)}
          >
            {days} 日
          </button>
        );
      })}
    </div>
  );
}
