const { Pool } = require('pg');
const sqlite3 = require('sqlite3').verbose();
const path = require('path');

const usePostgres = !!process.env.DATABASE_URL;
let pgPool = null;
let sqliteDb = null;

if (usePostgres) {
  console.log('Using Cloud PostgreSQL Database.');
  pgPool = new Pool({
    connectionString: process.env.DATABASE_URL,
    ssl: { rejectUnauthorized: false } // Required for hosting platforms like Render / Neon
  });
  initializeDatabase();
} else {
  console.log('Using Local SQLite Database.');
  const dbPath = path.resolve(__dirname, 'database.sqlite');
  sqliteDb = new sqlite3.Database(dbPath, (err) => {
    if (err) {
      console.error('Error opening database:', err);
    } else {
      console.log('Connected to the SQLite database.');
      initializeDatabase();
    }
  });
}

// Helper to convert database callbacks to Promises and support PostgreSQL
async function run(sql, params = []) {
  if (usePostgres) {
    let index = 1;
    let postgresSql = sql.replace(/\?/g, () => `$${index++}`);
    
    // Postgres compatibility: Convert SQLite "INSERT OR IGNORE" to PostgreSQL conflict resolution
    if (postgresSql.toUpperCase().includes('INSERT OR IGNORE')) {
      postgresSql = postgresSql.replace(/INSERT OR IGNORE/gi, 'INSERT');
      postgresSql += ' ON CONFLICT (username) DO NOTHING';
    }
    
    await pgPool.query(postgresSql, params);
  } else {
    return new Promise((resolve, reject) => {
      sqliteDb.run(sql, params, function (err) {
        if (err) reject(err);
        else resolve(this);
      });
    });
  }
}

async function get(sql, params = []) {
  if (usePostgres) {
    let index = 1;
    const postgresSql = sql.replace(/\?/g, () => `$${index++}`);
    const res = await pgPool.query(postgresSql, params);
    return res.rows[0] || null;
  } else {
    return new Promise((resolve, reject) => {
      sqliteDb.get(sql, params, (err, row) => {
        if (err) reject(err);
        else resolve(row);
      });
    });
  }
}

async function all(sql, params = []) {
  if (usePostgres) {
    let index = 1;
    const postgresSql = sql.replace(/\?/g, () => `$${index++}`);
    const res = await pgPool.query(postgresSql, params);
    return res.rows;
  } else {
    return new Promise((resolve, reject) => {
      sqliteDb.all(sql, params, (err, rows) => {
        if (err) reject(err);
        else resolve(rows);
      });
    });
  }
}

async function initializeDatabase() {
  if (usePostgres) {
    await pgPool.query(`
      CREATE TABLE IF NOT EXISTS subscriptions (
        id SERIAL PRIMARY KEY,
        username VARCHAR(255) UNIQUE NOT NULL,
        email VARCHAR(255) NOT NULL,
        license_key VARCHAR(255) UNIQUE NOT NULL,
        machine_id VARCHAR(255),
        status VARCHAR(50) DEFAULT 'ACTIVE',
        created_at VARCHAR(255) NOT NULL,
        expires_at VARCHAR(255) NOT NULL
      )
    `);
  } else {
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
  }

  // Insert a permanent testing account for localhost/development verification
  try {
    const dummyUser = 'rajesh1';
    const dummyEmail = 'rajesh1@gmail.com';
    const dummyKey = 'VELO-G8PT-JZ84-E6CE-VB3V';
    const created = new Date().toISOString();
    const expires = new Date();
    expires.setFullYear(expires.getFullYear() + 10); // 10 years expiry
    const expires_at = expires.toISOString();

    await run(`
      INSERT OR IGNORE INTO subscriptions (username, email, license_key, created_at, expires_at)
      VALUES (?, ?, ?, ?, ?)
    `, [dummyUser, dummyEmail, dummyKey, created, expires_at]);
    console.log('Testing account (rajesh1) verified/initialized.');
  } catch (err) {
    console.error('Failed to create testing account:', err);
  }

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

  if (sub.machine_id && sub.machine_id !== machineId) {
    return { 
      success: false, 
      message: 'This license is already registered on another computer. Please contact support to reset it.' 
    };
  }

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
    email: sub.email,
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
    email: sub.email,
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
