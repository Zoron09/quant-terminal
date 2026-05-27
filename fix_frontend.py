import re

with open('frontend/overview.html', 'r', encoding='utf-8') as f:
    code = f.read()

# 1. Valuation Tab
old_val = '''      const renderValuation = () => {
        if (!finData?.valuation) return <div style={{padding:'40px', textAlign:'center', color:'var(--fg-3)'}}>Loading...</div>;
        const v = finData.valuation;
        return (
          <table className="fin" style={{width: '50%'}}>
            <tbody>
              {Object.entries(v).map(([metric, val]) => {
                let display = '—';
                if (val != null) {
                  if (metric === 'ROE' || metric === 'ROA' || metric === 'Profit margin') {
                    display = (val * 100).toFixed(2) + '%';
                  } else {
                    display = val.toFixed(2);
                  }
                }
                return (
                  <tr key={metric}>
                    <td className="metric">{metric}</td>
                    <td className="num">{display}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        );
      };'''

new_val = '''      const renderValuation = () => {
        if (!finData?.valuation) return <div style={{padding:'40px', textAlign:'center', color:'var(--fg-3)'}}>Loading...</div>;
        const v = finData.valuation;
        
        const formatMetric = (metric, val) => {
          if (val == null || val === 'N/A') return '—';
          if (metric === 'ROE' || metric === 'ROA' || metric === 'Profit margin' || metric === 'Profit Margin') {
            const isPos = val > 0;
            const color = isPos ? 'var(--positive)' : 'var(--fg-1)';
            return <span style={{color}}>{(val * 100).toFixed(2) + '%'}</span>;
          }
          return val.toFixed(2);
        };

        const Card = ({ label, metricKey }) => (
          <div style={{ background: 'var(--bg-card)', border: '1px solid var(--fg-3)', borderRadius: '8px', padding: '16px 20px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
            <div style={{ color: 'var(--fg-2)', fontSize: '11px', textTransform: 'uppercase', fontWeight: 500 }}>{label}</div>
            <div style={{ color: 'var(--fg-1)', fontSize: '20px', fontWeight: 'bold', fontFamily: 'var(--font-mono)' }}>
              {formatMetric(label, v[metricKey] !== undefined ? v[metricKey] : v[label])}
            </div>
          </div>
        );

        return (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
            <div>
              <h3 style={{ color: '#D4A843', fontSize: '14px', textTransform: 'uppercase', marginBottom: '16px' }}>Multiples</h3>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '16px' }}>
                <Card label="P/E" metricKey="Trailing P/E" />
                <Card label="Forward P/E" metricKey="Forward P/E" />
                <Card label="P/S" metricKey="Price/Sales" />
                <Card label="P/B" metricKey="Price/Book" />
                <Card label="EV/EBITDA" metricKey="EV/EBITDA" />
                <Card label="EV/Revenue" metricKey="EV/Revenue" />
              </div>
            </div>
            <div>
              <h3 style={{ color: '#D4A843', fontSize: '14px', textTransform: 'uppercase', marginBottom: '16px' }}>Returns</h3>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '16px' }}>
                <Card label="ROE" metricKey="ROE" />
                <Card label="ROA" metricKey="ROA" />
                <Card label="Profit Margin" metricKey="Profit margin" />
              </div>
            </div>
            <div>
              <h3 style={{ color: '#D4A843', fontSize: '14px', textTransform: 'uppercase', marginBottom: '16px' }}>Leverage</h3>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '16px' }}>
                <Card label="Debt/Equity" metricKey="Debt/Equity" />
              </div>
            </div>
          </div>
        );
      };'''

code = code.replace(old_val, new_val)

# 2. IdentityBar Status Badge
old_id = '''      const compName = data?.company_name || (ticker === 'AMD' ? 'Advanced Micro Devices' : ticker);
      const price = data?.price ? `$${data.price.toFixed(2)}` : (ticker === 'AMD' ? '$467.51' : '---');
      const stat = data?.status || 'green';
      const statusColor = stat === 'green' ? 'var(--positive)' : stat === 'yellow' ? 'var(--warning)' : 'var(--fg-3)';
      const statusBg = stat === 'green' ? 'var(--positive-bg)' : stat === 'yellow' ? 'var(--warning-bg)' : 'transparent';
      const statusBorder = stat === 'green' ? 'var(--positive-border)' : stat === 'yellow' ? 'var(--warning-border)' : 'var(--border)';
      const statusText = stat === 'green' ? 'Code 33 Green' : stat === 'yellow' ? 'Code 33 Yellow' : 'Insufficient';'''

new_id = '''      const compName = data?.company_name || ticker;
      const price = data?.price ? `$${data.price.toFixed(2)}` : '---';
      const stat = data?.status || 'insufficient';
      
      const statusMap = {
        green: { color: 'var(--positive)', bg: 'var(--positive-bg)', border: 'var(--positive-border)', text: 'CODE 33 GREEN' },
        yellow: { color: 'var(--warning)', bg: 'var(--warning-bg)', border: 'var(--warning-border)', text: 'CODE 33 YELLOW' },
        red: { color: 'var(--negative)', bg: 'rgba(248,113,113,0.10)', border: 'rgba(248,113,113,0.30)', text: 'CODE 33 RED' },
        insufficient: { color: 'var(--fg-3)', bg: 'transparent', border: 'var(--border)', text: 'NO SIGNAL' }
      };
      
      const curStat = statusMap[stat] || statusMap['insufficient'];
      const statusColor = curStat.color;
      const statusBg = curStat.bg;
      const statusBorder = curStat.border;
      const statusText = curStat.text;'''

code = code.replace(old_id, new_id)

with open('frontend/overview.html', 'w', encoding='utf-8') as f:
    f.write(code)

