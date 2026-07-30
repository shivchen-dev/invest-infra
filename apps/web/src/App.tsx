import { useQuery } from "@tanstack/react-query";
import { fetchInstruments } from "./api";

export function App() {
  const query = useQuery({
    queryKey: ["instruments"],
    queryFn: fetchInstruments,
  });

  return (
    <main className="shell">
      <header>
        <p className="eyebrow">INVEST INFRA V2</p>
        <h1>投研数据工作台</h1>
        <p className="subtitle">首个垂直切片：Provider → PostgreSQL → FastAPI → React</p>
      </header>

      <section className="panel">
        <div className="panelHeader">
          <h2>标的主数据</h2>
          <span>{query.data?.items.length ?? 0} 条</span>
        </div>

        {query.isPending && <p>正在读取数据……</p>}
        {query.isError && <p className="error">{query.error.message}</p>}
        {query.data && (
          <table>
            <thead>
              <tr>
                <th>代码</th>
                <th>名称</th>
                <th>交易所</th>
                <th>类型</th>
              </tr>
            </thead>
            <tbody>
              {query.data.items.map((item) => (
                <tr key={item.symbol}>
                  <td>{item.symbol}</td>
                  <td>{item.name}</td>
                  <td>{item.exchange}</td>
                  <td>{item.instrument_type}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </main>
  );
}
