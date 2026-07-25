const sqlite3 = require('sqlite3').verbose();
const path = require('path');

const dbPath = path.resolve(__dirname, 'database.sqlite');
const db = new sqlite3.Database(dbPath, (err) => {
  if (err) {
    console.error('Error opening database:', err);
  } else {
    console.log('Connected to the SQLite database.');
    initializeDatabase();
  }
});

// Helper to convert database callbacks to Promises
function run(sql, params = []) {
  return new Promise((resolve, reject) => {
    db.run(sql, params, function (err) {
      if (err) reject(err);
      else resolve(this);
    });
  });
}

function get(sql, params = []) {
  return new Promise((resolve, reject) => {
    db.get(sql, params, (err, row) => {
      if (err) reject(err);
      else resolve(row);
    });
  });
}

function all(sql, params = []) {
  return new Promise((resolve, reject) => {
    db.all(sql, params, (err, rows) => {
      if (err) reject(err);
      else resolve(rows);
    });
  });
}

async function initializeDatabase() {
  await run(`
    CREATE TABLE IF NOT EXISTS subscriptions (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      username TEXT UNIQUE NOT NULL,
      email TEXT NOT NULL,
      license_key TEXT UNIQUE NOT NULL,
      machine_id TEXT,
      status TEXT DEFAULT 'ACTIVE',
      created_at TEXT NOT NULL,
      expires_at TEXT NOT NULL
    )
  `);
  console.log('Database tables initialized.');
}

async function getSubscription(usernameOrEmail) {
  const sql = `
    SELECT * FROM subscriptions 
    WHERE username = ? OR email = ?
  `;
  return await get(sql, [usernameOrEmail, usernameOrEmail]);
}

async function getSubscriptionByLicense(licenseKey) {
  const sql = `
    SELECT * FROM subscriptions 
    WHERE license_key = ?
  `;
  return await get(sql, [licenseKey]);
}

async function createSubscription(username, email, licenseKey) {
  const created_at = new Date().toISOString();
  // 1 year in the future
  const expires = new Date();
  expires.setFullYear(expires.getFullYear() + 1);
  const expires_at = expires.toISOString();

  const sql = `
    INSERT INTO subscriptions (username, email, license_key, created_at, expires_at)
    VALUES (?, ?, ?, ?, ?)
  `;
  await run(sql, [username, email, licenseKey, created_at, expires_at]);
  return { username, email, license_key: licenseKey, expires_at };
}

async function renewSubscription(usernameOrEmail) {
  const sub = await getSubscription(usernameOrEmail);
  if (!sub) {
    throw new Error('Subscription not found for renewal');
  }

  let currentExpiry = new Date(sub.expires_at);
  const now = new Date();
  
  // If already expired, start 1 year from now. Otherwise, add 1 year to current expiry.
  let newExpiry = currentExpiry > now ? currentExpiry : now;
  newExpiry.setFullYear(newExpiry.getFullYear() + 1);
  const new_expires_at = newExpiry.toISOString();

  const sql = `
    UPDATE subscriptions 
    SET expires_at = ?, status = 'ACTIVE'
    WHERE id = ?
  `;
  await run(sql, [new_expires_at, sub.id]);
  return { ...sub, expires_at: new_expires_at, status: 'ACTIVE' };
}

async function activateLicense(usernameOrEmail, licenseKey, machineId) {
  const sub = await getSubscription(usernameOrEmail);
  if (!sub) {
    return { success: false, message: 'No subscription found for this username or email.' };
  }

  if (sub.license_key !== licenseKey) {
    return { success: false, message: 'Invalid license key provided.' };
  }

  const now = new Date();
  const expiry = new Date(sub.expires_at);
  if (expiry < now) {
    return { success: false, message: 'Subscription has expired.' };
  }

  // Device binding check
  if (sub.machine_id && sub.machine_id !== machineId) {
    return { 
      success: false, 
      message: 'This license is already registered on another computer. Please contact support to reset it.' 
    };
  }

  // Bind device if not bound
  if (!sub.machine_id) {
    const sql = `
      UPDATE subscriptions 
      SET machine_id = ?
      WHERE id = ?
    `;
    await run(sql, [machineId, sub.id]);
  }

  return { 
    success: true, 
    username: sub.username, 
    expires_at: sub.expires_at,
    message: 'License activated successfully.' 
  };
}

async function verifyLicense(usernameOrEmail, licenseKey, machineId) {
  const sub = await getSubscription(usernameOrEmail);
  if (!sub) {
    return { success: false, message: 'Subscription not found.' };
  }

  if (sub.license_key !== licenseKey) {
    return { success: false, message: 'Invalid license key.' };
  }

  const now = new Date();
  const expiry = new Date(sub.expires_at);
  if (expiry < now) {
    return { success: false, message: 'Subscription has expired.' };
  }

  if (sub.machine_id && sub.machine_id !== machineId) {
    return { success: false, message: 'License key mismatch for this hardware.' };
  }

  return { 
    success: true, 
    username: sub.username, 
    expires_at: sub.expires_at,
    message: 'License is valid.' 
  };
}

module.exports = {
  getSubscription,
  getSubscriptionByLicense,
  createSubscription,
  renewSubscription,
  activateLicense,
  verifyLicense
};
